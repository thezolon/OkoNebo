#!/usr/bin/env python3
"""Fetch a safe-to-share support bundle from an OkoNebo instance."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys

import httpx


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fetch a redacted OkoNebo support bundle.")
    parser.add_argument(
        "--base-url",
        default=os.getenv("WEATHERAPP_BASE_URL", "http://localhost:8888"),
        help="Base URL for the OkoNebo instance (default: %(default)s)",
    )
    parser.add_argument(
        "--token",
        default=os.getenv("OKONEBO_BEARER_TOKEN", ""),
        help="Optional bearer token for auth-enabled instances.",
    )
    parser.add_argument(
        "--output",
        default="",
        help="Optional output path. Defaults to support_bundle_<UTC timestamp>.json in the current directory.",
    )
    return parser.parse_args()


def build_output_path(raw_output: str) -> Path:
    if raw_output:
        return Path(raw_output).expanduser().resolve()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return Path.cwd() / f"support_bundle_{stamp}.json"


def main() -> int:
    args = parse_args()
    url = f"{args.base_url.rstrip('/')}/api/support-bundle"
    headers = {"Authorization": f"Bearer {args.token}"} if args.token else None

    try:
        with httpx.Client(timeout=20, follow_redirects=True) as client:
            response = client.get(url, headers=headers)
        if response.status_code >= 400:
            print(
                f"Support bundle fetch failed with HTTP {response.status_code}: {response.text}",
                file=sys.stderr,
            )
            return 1
        payload = response.json()
    except Exception as exc:
        print(f"Support bundle fetch failed: {exc}", file=sys.stderr)
        return 1

    output_path = build_output_path(args.output)
    output_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(output_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())