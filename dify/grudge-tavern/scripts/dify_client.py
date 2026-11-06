"""Stdlib-only Dify console API client shared by the helper scripts.

Dify 1.17.1 console notes that this module encodes:
    * setup accepts a plaintext password; login expects it Base64-encoded
    * auth is cookie based (access_token / refresh_token / csrf_token)
    * every POST needs the CSRF cookie echoed in X-CSRF-Token
"""

from __future__ import annotations

import base64
import http.cookiejar
import json
import time
import urllib.error
import urllib.request


class DifyError(RuntimeError):
    pass


class DifyClient:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.jar)
        )
        self.csrf = ""

    def cookie(self, name: str) -> str:
        for item in self.jar:
            if item.name == name:
                return item.value or ""
        return ""

    def request(self, method: str, path: str, body: dict | None = None,
                timeout: int = 120) -> tuple[int, dict]:
        url = self.base_url + path
        data = None
        headers = {
            "Accept": "application/json",
            "User-Agent": "grudge-tavern-tools/1.0",
        }
        if body is not None:
            data = json.dumps(body, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        csrf = self.csrf or self.cookie("csrf_token")
        if csrf:
            headers["X-CSRF-Token"] = csrf
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with self.opener.open(req, timeout=timeout) as resp:
                raw = resp.read().decode("utf-8", "replace")
                return resp.status, (json.loads(raw) if raw else {})
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", "replace")
            try:
                payload = json.loads(raw) if raw else {}
            except json.JSONDecodeError:
                payload = {"raw": raw}
            return exc.code, payload
        except urllib.error.URLError as exc:
            raise DifyError(
                f"Cannot reach Dify at {self.base_url}: {exc.reason}. "
                "Is the web/nginx container up on this port?"
            ) from exc

    def api(self, method: str, path: str, body: dict | None = None,
            ok: tuple[int, ...] = (200, 201), timeout: int = 120) -> dict:
        status, payload = self.request(method, path, body, timeout=timeout)
        if status not in ok:
            raise DifyError(
                f"{method} {path} -> HTTP {status}: "
                f"{json.dumps(payload, ensure_ascii=False)[:800]}"
            )
        return payload

    def post_multipart(self, path: str, field: str, filename: str,
                       content: bytes, timeout: int = 180) -> tuple[int, dict]:
        boundary = f"----grudgetavern{int(time.time() * 1000)}"
        head = (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="{field}"; filename="{filename}"\r\n'
            "Content-Type: application/octet-stream\r\n\r\n"
        ).encode("utf-8")
        body = head + content + f"\r\n--{boundary}--\r\n".encode("utf-8")
        headers = {
            "Accept": "application/json",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "User-Agent": "grudge-tavern-tools/1.0",
        }
        csrf = self.csrf or self.cookie("csrf_token")
        if csrf:
            headers["X-CSRF-Token"] = csrf
        req = urllib.request.Request(
            self.base_url + path, data=body, headers=headers, method="POST"
        )
        try:
            with self.opener.open(req, timeout=timeout) as resp:
                raw = resp.read().decode("utf-8", "replace")
                return resp.status, (json.loads(raw) if raw else {})
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", "replace")
            try:
                payload = json.loads(raw) if raw else {}
            except json.JSONDecodeError:
                payload = {"raw": raw}
            return exc.code, payload


def ensure_setup(client: DifyClient, email: str, password: str, name: str,
                 init_password: str = "") -> None:
    status, payload = client.request("GET", "/console/api/setup")
    if status != 200:
        raise DifyError(f"GET /console/api/setup -> HTTP {status}: {payload}")
    if payload.get("step") == "finished":
        print("[setup] already initialized")
        return

    if init_password:
        status, payload = client.request(
            "POST", "/console/api/init", {"password": init_password}
        )
        if status not in (200, 201):
            raise DifyError(f"init password rejected: HTTP {status} {payload}")

    print("[setup] creating admin account")
    status, payload = client.request(
        "POST",
        "/console/api/setup",
        {
            "email": email,
            "name": name,
            "password": password,
            "language": "zh-Hans",
        },
    )
    if status in (200, 201) or payload.get("result") == "success":
        return
    if status == 400 and "already" in json.dumps(payload, ensure_ascii=False).lower():
        return
    raise DifyError(f"setup failed: HTTP {status} {payload}")


def login(client: DifyClient, email: str, password: str) -> None:
    encoded = base64.b64encode(password.encode("utf-8")).decode("ascii")
    status, payload = client.request(
        "POST",
        "/console/api/login",
        {
            "email": email,
            "password": encoded,
            "remember_me": True,
            "language": "zh-Hans",
        },
    )
    if status != 200 or payload.get("result") != "success":
        raise DifyError(
            f"login failed for {email}: HTTP {status} {payload}. "
            "Check DIFY_CONSOLE_EMAIL / DIFY_CONSOLE_PASSWORD."
        )
    client.csrf = client.cookie("csrf_token")
    if not client.csrf:
        raise DifyError("login succeeded but no csrf_token cookie was set")
    print(f"[login] ok as {email}")
