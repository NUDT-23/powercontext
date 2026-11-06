"""Minimal stdlib-only HTTP client shared by the helper scripts.

No third-party dependency is required so that judges can run the scripts with
a stock Python 3.10+ interpreter on Windows, macOS or Linux.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

DEFAULT_PC_URL = "http://127.0.0.1:8010"


class HttpError(RuntimeError):
    def __init__(self, status: int, body: str, url: str):
        self.status = status
        self.body = body
        self.url = url
        super().__init__(f"HTTP {status} from {url}: {body[:500]}")


def load_env_file(path: Path, override: bool = False) -> None:
    """Load KEY=VALUE lines from an env file without overwriting real env vars."""
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if override or key not in os.environ:
            os.environ[key] = value


def load_paths() -> tuple[Path, Path]:
    scripts_dir = Path(__file__).resolve().parent
    dify_dir = scripts_dir.parent
    return dify_dir, dify_dir / ".local"


def env(name: str, default: str = "") -> str:
    return (os.environ.get(name) or default).strip()


def pc_url() -> str:
    return env("PC_URL", DEFAULT_PC_URL).rstrip("/")


def token() -> str:
    return env("PC_TOKEN")


def _request(method: str, url: str, body: dict | None = None, timeout: int = 30) -> dict:
    data = None
    headers = {"Accept": "application/json"}
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if token():
        headers["Authorization"] = f"Bearer {token()}"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = resp.read().decode("utf-8")
            return json.loads(payload) if payload else {}
    except urllib.error.HTTPError as exc:
        raise HttpError(exc.code, exc.read().decode("utf-8", "replace"), url) from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(
            f"Cannot reach {url}: {exc.reason}. Is PowerContext running "
            f"(docker compose ... up -d powercontext)?"
        ) from exc


def get(path: str, timeout: int = 30) -> dict:
    return _request("GET", pc_url() + path, timeout=timeout)


def post(path: str, body: dict, timeout: int = 30) -> dict:
    return _request("POST", pc_url() + path, body, timeout=timeout)


def wait_ready(timeout_seconds: int = 90) -> dict:
    import time

    deadline = time.time() + timeout_seconds
    last_error: Exception | None = None
    while time.time() < deadline:
        try:
            return get("/health/ready", timeout=5)
        except Exception as exc:  # noqa: BLE001 - retry until deadline
            last_error = exc
            time.sleep(2)
    raise RuntimeError(f"PowerContext did not become ready: {last_error}")


def dump_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def die(message: str) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)
