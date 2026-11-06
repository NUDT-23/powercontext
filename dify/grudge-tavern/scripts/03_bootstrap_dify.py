#!/usr/bin/env python3
"""Bootstrap a local Dify instance for the Grudge Tavern app.

What it does (all through Dify's console API, no browser required):
    1. POST /console/api/setup          initialize the admin account (once)
    2. POST /console/api/login          login with Base64-encoded password
    3. install the Anthropic model plugin from the Dify marketplace
       (falls back to the OpenAI-API-compatible plugin for DeepSeek)
    4. store the model provider credentials
    5. import .local/app.local.yaml, confirm a pending import if needed
    6. publish the workflow and create an app API key
    7. write .local/dify.json with app id + API key

Requires scripts/02_render_dsl.py to have produced .local/app.local.yaml.

Environment (loaded from grudge-tavern/.env, grudge-tavern/compose/.env, or the process):
    DIFY_BASE_URL            default http://127.0.0.1:8088
    DIFY_CONSOLE_EMAIL       admin email used for setup/login
    DIFY_CONSOLE_PASSWORD    admin password used for setup/login
    DIFY_CONSOLE_NAME        display name (default "Grudge Tavern")
    INIT_PASSWORD            only when the server sets init_password
    ANTHROPIC_BASE_URL       proxied Anthropic API root (e.g. https://api.deepseek.com/anthropic)
    ANTHROPIC_AUTH_TOKEN     API key for the above
    DIFY_LLM_MODEL           override the model name baked into the DSL
    OPENAI_COMPAT_BASE_URL   fallback OpenAI-compatible base URL
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pc_client as pc  # noqa: E402
from dify_client import DifyClient, DifyError, ensure_setup, login  # noqa: E402

MARKETPLACE_API = "https://marketplace.dify.ai/api/v1/plugins"
ANTHROPIC_PROVIDER = "langgenius/anthropic/anthropic"
OPENAI_COMPAT_PROVIDER = "langgenius/openai_api_compatible/openai_api_compatible"
DEFAULT_ANTHROPIC_MODEL = "claude-sonnet-4-6"
DEFAULT_OPENAI_MODEL = "deepseek-chat"


def marketplace_identifier(plugin_id: str, env_name: str) -> str:
    override = pc.env(env_name)
    if override:
        return override
    url = f"{MARKETPLACE_API}/{plugin_id}"
    req = urllib.request.Request(url, headers={"User-Agent": "curl/8"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        identifier = data["data"]["plugin"]["latest_package_identifier"]
    except Exception as exc:  # noqa: BLE001 - surfaced with instructions
        raise DifyError(
            f"Cannot resolve {plugin_id} from the marketplace ({exc}). "
            f"Set {env_name}=<org/name:version@checksum> manually."
        ) from exc
    print(f"[plugin] {plugin_id} -> {identifier}")
    return identifier


def wait_install_task(client: DifyClient, payload: dict, timeout: int = 300) -> None:
    if payload.get("all_installed"):
        return
    task_id = payload.get("task_id")
    if not task_id:
        raise DifyError(f"plugin install returned no task id: {payload}")
    print(f"[plugin] install task {task_id}")
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        status, payload = client.request(
            "GET", f"/console/api/workspaces/current/plugin/tasks/{task_id}"
        )
        if status == 200:
            task = payload.get("task") or {}
            last = task
            state = task.get("status")
            if state == "success":
                print("[plugin] install complete")
                return
            if state == "failed":
                failed = [
                    p.get("message")
                    for p in (task.get("plugins") or [])
                    if p.get("status") == "failed"
                ]
                raise DifyError(f"plugin install task failed: {failed or task}")
        time.sleep(3)
    raise DifyError(f"plugin install timed out after {timeout}s: {last}")


def install_plugin(client: DifyClient, plugin_id: str, identifier: str) -> None:
    status, payload = client.request(
        "POST",
        "/console/api/workspaces/current/plugin/install/marketplace",
        {"plugin_unique_identifiers": [identifier]},
        timeout=60,
    )
    if status == 200:
        if payload.get("all_installed"):
            print(f"[plugin] already installed: {identifier}")
            return
        wait_install_task(client, payload)
        return

    print(
        f"[plugin] marketplace install failed (HTTP {status}); "
        "uploading the package directly"
    )
    version = identifier.split(":", 1)[-1].split("@", 1)[0]
    url = f"{MARKETPLACE_API}/{plugin_id}/{version}/download"
    req = urllib.request.Request(url, headers={"User-Agent": "curl/8"})
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            package = resp.read()
        status, decoded = client.post_multipart(
            "/console/api/workspaces/current/plugin/upload/pkg",
            field="pkg",
            filename="plugin.difypkg",
            content=package,
        )
    except Exception as exc:  # noqa: BLE001 - surfaced to the operator
        raise DifyError(f"plugin package upload failed: {exc}") from exc
    if status != 200:
        raise DifyError(f"plugin package upload failed: HTTP {status} {decoded}")
    uploaded = decoded.get("unique_identifier") or identifier
    status, payload = client.request(
        "POST",
        "/console/api/workspaces/current/plugin/install/pkg",
        {"plugin_unique_identifiers": [uploaded]},
        timeout=60,
    )
    if status != 200:
        raise DifyError(f"plugin install from package failed: HTTP {status} {payload}")
    wait_install_task(client, payload)


def ensure_anthropic(
    client: DifyClient, api_url: str, api_key: str
) -> str:
    path = (
        "/console/api/workspaces/current/model-providers/"
        f"{ANTHROPIC_PROVIDER}/credentials"
    )
    status, payload = client.request("GET", path)
    if status == 200:
        existing = payload.get("credentials") or {}
        if existing.get("anthropic_api_key"):
            print("[model] anthropic credentials already configured")
            return ANTHROPIC_PROVIDER

    credentials = {"anthropic_api_key": api_key}
    if api_url:
        credentials["anthropic_api_url"] = api_url
    print(f"[model] saving anthropic credentials (url={api_url or 'default'})")
    status, payload = client.request(
        "POST", path, {"credentials": credentials, "name": "competition"}
    )
    if status not in (200, 201):
        raise DifyError(f"anthropic credential rejected: HTTP {status} {payload}")
    return ANTHROPIC_PROVIDER


def ensure_openai_compatible(
    client: DifyClient, base_url: str, api_key: str, model: str
) -> str:
    path = (
        "/console/api/workspaces/current/model-providers/"
        f"{OPENAI_COMPAT_PROVIDER}/models/credentials"
    )
    credentials = {
        "endpoint_url": base_url,
        "api_key": api_key,
        "mode": "chat",
        "context_size": "65536",
    }
    print(f"[model] saving OpenAI-compatible model {model} -> {base_url}")
    status, payload = client.request(
        "POST",
        path,
        {
            "model": model,
            "model_type": "llm",
            "credentials": credentials,
            "name": "DeepSeek chat",
        },
    )
    if status in (200, 201):
        return OPENAI_COMPAT_PROVIDER
    if status == 400 and "exist" in json.dumps(payload, ensure_ascii=False).lower():
        print("[model] OpenAI-compatible model already exists")
        return OPENAI_COMPAT_PROVIDER
    raise DifyError(f"OpenAI-compatible model rejected: HTTP {status} {payload}")


def patch_dsl_model(yaml_text: str, provider: str, model: str) -> str:
    patched = yaml_text.replace(
        "provider: langgenius/anthropic/anthropic", f"provider: {provider}"
    ).replace(f"name: {DEFAULT_ANTHROPIC_MODEL}", f"name: {model}")
    if f"provider: {provider}" not in patched or f"name: {model}" not in patched:
        raise DifyError(
            "Could not patch the LLM node model in the rendered DSL; "
            "check app/grudge-tavern.dsl.yaml."
        )
    return patched


def import_app(client: DifyClient, yaml_text: str, app_id: str | None) -> dict:
    body = {"mode": "yaml-content", "yaml_content": yaml_text}
    if app_id:
        body["app_id"] = app_id
    status, payload = client.request("POST", "/console/api/apps/imports", body)
    if status == 202:
        import_id = payload.get("id")
        if not import_id:
            raise DifyError(f"pending import without id: {payload}")
        print(f"[import] confirming pending import {import_id}")
        status, payload = client.request(
            "POST", f"/console/api/apps/imports/{import_id}/confirm", {}
        )
    if status in (200, 202) and payload.get("status") in (
        "completed",
        "completed-with-warnings",
    ):
        if payload.get("warnings"):
            print(f"[import] warnings: {payload['warnings']}")
        return payload
    if app_id:
        print(f"[import] update of existing app failed ({status} {payload}); importing as new app")
        return import_app(client, yaml_text, None)
    raise DifyError(
        f"DSL import failed: HTTP {status} "
        f"{json.dumps(payload, ensure_ascii=False)[:1200]}"
    )


def publish_app(client: DifyClient, app_id: str) -> None:
    status, payload = client.request(
        "POST",
        f"/console/api/apps/{app_id}/workflows/publish",
        {"marked_name": "competition", "marked_comment": "记仇酒馆自动发布"},
    )
    if status != 200:
        raise DifyError(f"publish failed: HTTP {status} {payload}")
    print(f"[publish] workflow published for app {app_id}")


def create_api_key(client: DifyClient, app_id: str) -> str:
    override = pc.env("DIFY_APP_API_KEY")
    if override:
        print("[api-key] using DIFY_APP_API_KEY from env")
        return override
    status, payload = client.request(
        "POST", f"/console/api/apps/{app_id}/api-keys"
    )
    if status not in (200, 201) or not payload.get("token"):
        raise DifyError(f"API key creation failed: HTTP {status} {payload}")
    print("[api-key] created app key")
    return payload["token"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dsl", default=".local/app.local.yaml")
    parser.add_argument(
        "--provider",
        choices=["auto", "anthropic", "openai-compatible"],
        default="auto",
        help="Model provider to configure (auto = anthropic, fall back to OpenAI-compatible)",
    )
    args = parser.parse_args()

    dify_dir, local_dir = pc.load_paths()
    pc.load_env_file(dify_dir / ".env")
    pc.load_env_file(dify_dir / "compose" / ".env")

    dsl_path = (dify_dir / args.dsl).resolve()
    if not dsl_path.is_file():
        pc.die(
            f"Rendered DSL not found: {dsl_path}. "
            "Run scripts/02_render_dsl.py first."
        )
    yaml_text = dsl_path.read_text(encoding="utf-8")
    if "__PC_" in yaml_text:
        pc.die("Rendered DSL still contains placeholders; re-run 02_render_dsl.py.")

    base_url = pc.env("DIFY_BASE_URL", "http://127.0.0.1:8088")
    email = pc.env("DIFY_CONSOLE_EMAIL")
    password = pc.env("DIFY_CONSOLE_PASSWORD")
    if not email or not password:
        pc.die("Set DIFY_CONSOLE_EMAIL and DIFY_CONSOLE_PASSWORD in dify/.env.")

    state_file = local_dir / "dify.json"
    state = {}
    if state_file.is_file():
        state = json.loads(state_file.read_text(encoding="utf-8"))

    client = DifyClient(base_url)
    ensure_setup(
        client,
        email,
        password,
        pc.env("DIFY_CONSOLE_NAME", "Grudge Tavern"),
        pc.env("INIT_PASSWORD"),
    )
    login(client, email, password)

    provider = ""
    model = ""
    if args.provider in ("auto", "anthropic"):
        try:
            identifier = marketplace_identifier(
                "langgenius/anthropic", "ANTHROPIC_PLUGIN_IDENTIFIER"
            )
            install_plugin(client, "langgenius/anthropic", identifier)
            provider = ensure_anthropic(
                client, pc.env("ANTHROPIC_BASE_URL"), pc.env("ANTHROPIC_AUTH_TOKEN")
            )
            model = pc.env("DIFY_LLM_MODEL", DEFAULT_ANTHROPIC_MODEL)
        except (DifyError, KeyError) as exc:
            if args.provider == "anthropic":
                raise
            print(f"[model] anthropic unavailable ({exc}); using OpenAI-compatible fallback")
            provider = ""

    if not provider:
        identifier = marketplace_identifier(
            "langgenius/openai_api_compatible", "OPENAI_COMPAT_PLUGIN_IDENTIFIER"
        )
        install_plugin(client, "langgenius/openai_api_compatible", identifier)
        model = pc.env("DIFY_LLM_MODEL", DEFAULT_OPENAI_MODEL)
        provider = ensure_openai_compatible(
            client,
            pc.env("OPENAI_COMPAT_BASE_URL", "https://api.deepseek.com/v1"),
            pc.env("ANTHROPIC_AUTH_TOKEN") or pc.env("OPENAI_API_KEY"),
            model,
        )

    if provider != ANTHROPIC_PROVIDER or model != DEFAULT_ANTHROPIC_MODEL:
        yaml_text = patch_dsl_model(yaml_text, provider, model)

    result = import_app(client, yaml_text, state.get("app_id"))
    app_id = result.get("app_id")
    if not app_id:
        raise DifyError(f"import completed without an app id: {result}")
    state.update(
        {
            "base_url": base_url,
            "app_id": app_id,
            "app_mode": result.get("app_mode"),
            "imported_dsl_version": result.get("imported_dsl_version"),
            "provider": provider,
            "model": model,
        }
    )
    pc.dump_json(state_file, state)

    publish_app(client, app_id)
    state["api_key"] = create_api_key(client, app_id)
    pc.dump_json(state_file, state)

    print()
    print(f"App ready: {base_url}/app/{app_id}/workflow")
    print(f"Service API key: {state['api_key'][:8]}… (saved in .local/dify.json)")
    print("Next: python scripts/04_verify.py")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except DifyError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
