from __future__ import annotations

import json
import os

import httpx

BASE_URL = os.environ.get("APP_URL", "http://127.0.0.1:8000")


def main() -> None:
    with httpx.Client(timeout=600.0) as client:
        response = client.post(f"{BASE_URL}/api/dev/seed")
    response.raise_for_status()
    print(json.dumps(response.json(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
