"""Local operator controls for supervised bench and movement checks."""

import argparse
from getpass import getpass

import httpx

from .config import Settings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["status", "stop", "drive", "turn", "auto_step"])
    parser.add_argument("--port", type=int, default=8000, help="Local Currator HTTP port")
    args = parser.parse_args()
    token = Settings().robot_operator_token or getpass("Operator token: ")
    try:
        with httpx.Client(
            base_url=f"http://127.0.0.1:{args.port}", timeout=3, trust_env=False,
            headers={"X-Operator-Token": token},
        ) as client:
            if args.action == "status":
                response = client.get("/api/robot/status")
            else:
                response = client.post("/api/robot/command", json={"action": args.action})
            print(response.text)
            return 0 if response.is_success else 1
    except httpx.HTTPError:
        print("Could not reach the local Currator server.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
