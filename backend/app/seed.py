from __future__ import annotations

import argparse
import json
import os

import httpx

BASE_URL = os.environ.get("APP_URL", "http://127.0.0.1:8000")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trials", type=int, default=0, help="create N per-tester trial projects")
    args = parser.parse_args()

    with httpx.Client(timeout=600.0) as client:
        if args.trials > 0:
            response = client.post(
                f"{BASE_URL}/api/dev/trial_projects", params={"users": args.trials}
            )
        else:
            response = client.post(f"{BASE_URL}/api/dev/seed")
    response.raise_for_status()
    print(json.dumps(response.json(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
