#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

LEDGER_ROOT = Path("/home/omar/11-Pilotage/ledgers/builds")


def main() -> None:
    parser = argparse.ArgumentParser(description="Record an OA build/deploy proof into the daily QG ledger.")
    parser.add_argument("--repo", required=True, help="Repository slug, e.g. omar-paris/omar-qg")
    parser.add_argument("--command", required=True, help="Build/test/deploy command that was run")
    parser.add_argument("--status", required=True, choices=["success", "failure", "blocked"], help="Outcome")
    parser.add_argument("--version", default="", help="Visible version/build marker")
    parser.add_argument("--url", default="", help="Verified URL, if any")
    parser.add_argument("--http-code", type=int, default=None, help="HTTP status from smoke probe, if any")
    parser.add_argument("--pr", default="", help="PR number or URL, if any")
    parser.add_argument("--notes", default="", help="Short factual note")
    args = parser.parse_args()

    ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    day = time.strftime("%Y-%m-%d", time.localtime())
    LEDGER_ROOT.mkdir(parents=True, exist_ok=True)
    row = {
        "timestamp": ts,
        "repo": args.repo,
        "command": args.command,
        "status": args.status,
        "version": args.version,
        "url": args.url,
        "http_code": args.http_code,
        "pr": args.pr,
        "notes": args.notes,
    }
    out = LEDGER_ROOT / f"{day}.jsonl"
    with out.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    print(str(out))


if __name__ == "__main__":
    main()
