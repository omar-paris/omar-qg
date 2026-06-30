#!/usr/bin/env python3
"""Collect the governed Issue → Kanban → PR → Gate → Merge registry for QG.

Read-only by design: it republishes durable artifacts already produced by H-Omar/agents.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

DEFAULT_SEED = Path(os.environ.get(
    "OA_AGENT_LOOP_REGISTRY_SEED",
    "/home/omar/11-Pilotage/sujets-actifs/oa-consolidation-production/oa_registry_min_p4_seed_2026-06-30.json",
))
SCHEMA = "oa.agent-loop-registry/1"


def _empty(source: Path = DEFAULT_SEED, error: str | None = None) -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "status": "empty" if error is None else "degraded",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "source": str(source),
        "summary": {"issues": 0, "cards": 0, "prs": 0, "gates": 0, "merges": 0, "artifacts": 0},
        "items": [],
        "errors": [] if error is None else [error],
    }


def collect(seed_path: str | Path = DEFAULT_SEED) -> dict[str, Any]:
    path = Path(seed_path)
    if not path.exists():
        return _empty(path, f"seed missing: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # keep QG build resilient
        return _empty(path, f"seed unreadable: {exc.__class__.__name__}")

    raw_items = payload.get("items")
    if isinstance(raw_items, list):
        items = raw_items
    else:
        items: list[dict[str, Any]] = []
        pr = payload.get("github_pr")
        if isinstance(pr, dict):
            items.append({"kind": "pr", **pr})
            if str(pr.get("state", "")).upper() == "MERGED":
                items.append({
                    "kind": "merge",
                    "number": pr.get("number"),
                    "url": pr.get("url"),
                    "mergedAt": pr.get("mergedAt"),
                    "mergeCommit": pr.get("mergeCommit"),
                })
        for task in payload.get("kanban_tasks") or []:
            if isinstance(task, dict):
                title = str(task.get("title") or "")
                kind = "gate" if any(token in title.lower() for token in ("athena", "review", "gate")) else "card"
                items.append({"kind": kind, **task})
        for artifact in payload.get("artifacts") or []:
            items.append({"kind": "artifact", "path": str(artifact)})

    def count(kind: str) -> int:
        return sum(1 for item in items if str(item.get("kind", "")).lower() == kind)

    # Current seed is minimal and may not type every object. Preserve explicit counts if present.
    raw_summary = payload.get("summary")
    source_summary: dict[str, Any] = raw_summary if isinstance(raw_summary, dict) else {}
    summary = {
        "issues": int(source_summary.get("issues") or count("issue")),
        "cards": int(source_summary.get("cards") or count("card")),
        "prs": int(source_summary.get("prs") or count("pr")),
        "gates": int(source_summary.get("gates") or count("gate")),
        "merges": int(source_summary.get("merges") or count("merge")),
        "artifacts": int(source_summary.get("artifacts") or count("artifact")),
    }

    return {
        "schema": SCHEMA,
        "status": "healthy" if items else "empty",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "source": str(path),
        "seed_schema": payload.get("schema"),
        "summary": summary,
        "items": items,
        "proofs": payload.get("proofs") or payload.get("evidence") or [],
        "errors": [],
    }


if __name__ == "__main__":
    print(json.dumps(collect(), ensure_ascii=False, indent=2))
