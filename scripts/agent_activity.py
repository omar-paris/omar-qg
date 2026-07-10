#!/usr/bin/env python3
"""Collect a redacted dynamic agent activity snapshot for OA QG.

Source of truth is local Hermes Kanban + agent registry. This is read-only: it
summarizes work ownership, priorities, VPS/application hints, artifacts/results,
and freshness so Alex can answer: who does what, where, why, and what next?
"""
from __future__ import annotations

import json
import re
import sqlite3
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA = "oa.agent-activity/v1"
KANBAN_DB = Path("/home/omar/.hermes/kanban.db")
AGENT_REGISTRY = Path("/home/omar/31-Agents/registry/agent_registry.json")
ARTIFACT_ROOT = Path("/home/omar/.hermes/kanban/artifacts")

SECRET_PATTERNS = [
    re.compile(r"gh[pousr]_[A-Za-z0-9_]{20,}"),
    re.compile(r"sk-[A-Za-z0-9_-]{20,}"),
    re.compile(r"xox[baprs]-[A-Za-z0-9-]{20,}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.S),
    re.compile(r"(?i)(authorization|api[_-]?key|token|password|secret)\s*[:=]\s*[^\s]+"),
    re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b"),
]

AGENT_VPS_HINTS = {
    "default": "VPS-Omar",
    "oa-builder": "VPS-Omar",
    "oa-athena": "VPS-Omar",
    "oa-audit": "VPS-Omar",
    "oa-vps-operator": "VPS-Omar",
    "hm-tech": "VPS-Omar",
    "hm-focus": "VPS-Omar",
    "hm-biz": "VPS-Omar",
    "h-aurel": "Pantheos",
    "cc-client-ubuntu": "VPS clients",
    "cc-client-windows": "PC Alex",
}

VPS_KEYWORDS = {
    "pantheos": "Pantheos",
    "alexgo": "Pantheos",
    "hugo": "Pantheos",
    "theo": "Pantheos",
    "victoria": "Pantheos",
    "jab": "JAB",
    "client ubuntu": "VPS clients",
    "cccu": "VPS clients",
    "vps-omar": "VPS-Omar",
    "omar": "VPS-Omar",
}

APP_KEYWORDS = {
    "appomar": "AppOmar",
    "omar-app": "AppOmar",
    "audit": "AppOmar/audit",
    "qg": "QG",
    "hub": "Hub",
    "catalogue": "Catalogue",
    "omartop": "OmarTop",
    "landing": "Landing",
    "langfuse": "Langfuse",
    "kanban": "Kanban",
    "hermes": "Hermes",
}

TYPE_KEYWORDS = [
    ("security", ["security", "sudo", "ssh", "secret", "vault", "hardening", "sécurité"]),
    ("review_gate", ["athena", "gate", "review", "verdict"]),
    ("build", ["builder", "build", "implément", "implement", "fix", "patch"]),
    ("deploy_smoke", ["deploy", "smoke", "release", "merge", "pr #"]),
    ("observability", ["telemetry", "télémétrie", "langfuse", "observability", "activity", "trace"]),
    ("product", ["audit", "ux", "conversation", "client", "onboarding"]),
    ("ops", ["vps", "caddy", "systemd", "infra", "kanban", "cron"]),
]


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _iso(ts: Any) -> str | None:
    if ts in (None, ""):
        return None
    try:
        return datetime.fromtimestamp(int(ts), tz=timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    except Exception:
        return None


def _redact(text: Any, limit: int = 700) -> str:
    s = "" if text is None else str(text)
    for pat in SECRET_PATTERNS:
        s = pat.sub("[REDACTED]", s)
    # Public QG output must not expose local control-plane paths, even shortened
    # as ~/.hermes. Keep logical refs elsewhere (kanban-artifact:...) instead.
    s = re.sub(r"/home/omar/[^\s)'\"]+", "[INTERNAL_PATH]", s)
    s = re.sub(r"~/\.hermes(?:/[^\s)'\"]*)?", "[INTERNAL_PATH]", s)
    s = re.sub(r"/\.hermes(?:/[^\s)'\"]*)?", "[INTERNAL_PATH]", s)
    s = re.sub(r"[A-Za-z0-9_.-]*\.hermes(?:/[^\s)'\"]*)?", "[INTERNAL_PATH]", s)
    s = re.sub(r"\s+", " ", s).strip()
    if len(s) > limit:
        return s[: limit - 1].rstrip() + "…"
    return s


def _priority_bucket(priority: Any) -> str:
    try:
        p = int(priority or 0)
    except Exception:
        p = 0
    if p >= 100:
        return "P0"
    if p >= 80:
        return "P1"
    if p >= 50:
        return "P2"
    return "P3"


def _text_blob(row: dict[str, Any]) -> str:
    return " ".join(str(row.get(k) or "") for k in ("title", "body", "result", "idempotency_key", "workspace_path")).lower()


def _infer_vps(row: dict[str, Any], assignee: str) -> str:
    blob = _text_blob(row)
    for key, label in VPS_KEYWORDS.items():
        if key in blob:
            return label
    return AGENT_VPS_HINTS.get(assignee, "unknown")


def _infer_app(row: dict[str, Any]) -> str:
    blob = _text_blob(row)
    for key, label in APP_KEYWORDS.items():
        if key in blob:
            return label
    project = row.get("project_id")
    if project:
        return str(project)
    return "unknown"


def _infer_activity_type(row: dict[str, Any]) -> str:
    blob = _text_blob(row)
    for kind, words in TYPE_KEYWORDS:
        if any(w in blob for w in words):
            return kind
    return "work_item"


def _artifact_refs(task_id: str) -> list[dict[str, str]]:
    base = ARTIFACT_ROOT / task_id
    if not base.exists() or not base.is_dir():
        return []
    refs: list[dict[str, str]] = []
    for p in sorted(base.iterdir(), key=lambda x: x.stat().st_mtime if x.exists() else 0, reverse=True)[:8]:
        if p.is_file():
            safe_name = _redact(p.name, 120)
            refs.append({"name": safe_name, "ref": f"kanban-artifact:{task_id}/{safe_name}"})
    return refs


def _load_registry_agents() -> dict[str, dict[str, Any]]:
    try:
        payload = json.loads(AGENT_REGISTRY.read_text(encoding="utf-8"))
    except Exception:
        return {}
    out: dict[str, dict[str, Any]] = {}
    for agent in payload.get("agents") or []:
        if not isinstance(agent, dict):
            continue
        name = (((agent.get("identity") or {}).get("name")) or agent.get("agent_key") or "").strip()
        if not name:
            continue
        out[name] = {
            "agent_key": agent.get("agent_key"),
            "framework": agent.get("framework"),
            "role": (agent.get("identity") or {}).get("role_declared"),
            "kanban_seen": (agent.get("cross_system_refs") or {}).get("kanban_seen"),
            "compliance": (agent.get("compliance") or {}).get("status"),
        }
    return out


def _query_tasks(window_days: int, limit: int) -> tuple[list[dict[str, Any]], list[str]]:
    errors: list[str] = []
    if not KANBAN_DB.exists():
        return [], [_redact(f"kanban db missing: {KANBAN_DB}")]
    cutoff = int(time.time()) - window_days * 86400
    try:
        con = sqlite3.connect(str(KANBAN_DB))
        con.row_factory = sqlite3.Row
        rows = con.execute(
            """
            SELECT t.*, r.id AS run_id, r.profile AS run_profile, r.status AS run_status,
                   r.started_at AS run_started_at, r.ended_at AS run_ended_at,
                   r.outcome AS run_outcome, r.error AS run_error
            FROM tasks t
            LEFT JOIN task_runs r ON r.id = t.current_run_id
            WHERE COALESCE(t.completed_at, t.started_at, t.created_at, 0) >= ?
               OR t.status IN ('running','ready','blocked','scheduled','todo')
            ORDER BY COALESCE(t.completed_at, t.started_at, t.created_at, 0) DESC
            LIMIT ?
            """,
            (cutoff, limit),
        ).fetchall()
        return [dict(r) for r in rows], errors
    except Exception as exc:
        return [], [_redact(f"kanban query failed: {exc.__class__.__name__}: {exc}")]


def collect(window_days: int = 7, limit: int = 240) -> dict[str, Any]:
    rows, errors = _query_tasks(window_days, limit)
    registry = _load_registry_agents()
    items: list[dict[str, Any]] = []
    by_agent: dict[str, dict[str, Any]] = defaultdict(lambda: {
        "total": 0, "active": 0, "done": 0, "blocked": 0, "ready": 0, "latest_at": None,
        "priorities": Counter(), "types": Counter(), "vps": Counter(), "apps": Counter(),
    })
    by_vps: Counter[str] = Counter()
    by_type: Counter[str] = Counter()
    by_status: Counter[str] = Counter()
    by_priority: Counter[str] = Counter()
    now = int(time.time())

    for row in rows:
        assignee = str(row.get("assignee") or row.get("run_profile") or "unassigned")
        status = str(row.get("status") or "unknown")
        p_bucket = _priority_bucket(row.get("priority"))
        vps = _infer_vps(row, assignee)
        app = _infer_app(row)
        kind = _infer_activity_type(row)
        latest_ts = row.get("completed_at") or row.get("started_at") or row.get("created_at")
        heartbeat = row.get("last_heartbeat_at") or row.get("run_started_at")
        stale_minutes = None
        if status == "running" and heartbeat:
            try:
                stale_minutes = max(0, int((now - int(heartbeat)) / 60))
            except Exception:
                stale_minutes = None
        item = {
            "task_id": row.get("id"),
            "title": _redact(row.get("title"), 180),
            "assignee": assignee,
            "agent_role": _redact((registry.get(assignee) or {}).get("role"), 180),
            "status": status,
            "priority": int(row.get("priority") or 0),
            "priority_bucket": p_bucket,
            "vps": vps,
            "application": app,
            "activity_type": kind,
            "created_at": _iso(row.get("created_at")),
            "started_at": _iso(row.get("started_at")),
            "completed_at": _iso(row.get("completed_at")),
            "latest_at": _iso(latest_ts),
            "stale_minutes": stale_minutes,
            "result_excerpt": _redact(row.get("result"), 360),
            "next_action": _redact(row.get("last_failure_error") or row.get("block_kind") or "", 180),
            "workspace_kind": row.get("workspace_kind"),
            "project_id": row.get("project_id"),
            "run": {
                "id": row.get("run_id"),
                "profile": row.get("run_profile"),
                "status": row.get("run_status"),
                "outcome": _redact(row.get("run_outcome"), 180),
                "error": _redact(row.get("run_error"), 180),
            },
            "artifacts": _artifact_refs(str(row.get("id") or "")),
        }
        items.append(item)
        agent = by_agent[assignee]
        agent["total"] += 1
        if status in {"running", "ready", "todo", "scheduled"}:
            agent["active"] += 1
        if status == "done":
            agent["done"] += 1
        if status == "blocked":
            agent["blocked"] += 1
        if status == "ready":
            agent["ready"] += 1
        agent["priorities"][p_bucket] += 1
        agent["types"][kind] += 1
        agent["vps"][vps] += 1
        agent["apps"][app] += 1
        if latest_ts and (agent["latest_at"] is None or int(latest_ts) > int(agent["latest_at"])):
            agent["latest_at"] = int(latest_ts)
        by_vps[vps] += 1
        by_type[kind] += 1
        by_status[status] += 1
        by_priority[p_bucket] += 1

    agents = []
    for name, data in by_agent.items():
        meta = registry.get(name) or {}
        agents.append({
            "agent": name,
            "role": _redact(meta.get("role"), 220),
            "framework": meta.get("framework"),
            "compliance": meta.get("compliance"),
            "kanban_seen": meta.get("kanban_seen"),
            "total": data["total"],
            "active": data["active"],
            "done": data["done"],
            "blocked": data["blocked"],
            "ready": data["ready"],
            "latest_at": _iso(data["latest_at"]),
            "dominant_vps": data["vps"].most_common(1)[0][0] if data["vps"] else "unknown",
            "dominant_type": data["types"].most_common(1)[0][0] if data["types"] else "unknown",
            "priorities": dict(data["priorities"]),
            "types": dict(data["types"]),
            "vps": dict(data["vps"]),
            "applications": dict(data["apps"]),
        })
    agents.sort(key=lambda x: (x["active"], x["total"], x.get("latest_at") or ""), reverse=True)

    active_items = [i for i in items if i["status"] in {"running", "ready", "todo", "scheduled", "blocked"}]
    decision_required = [i for i in items if i["status"] == "blocked" or "GO REQUIRED" in i["title"] or "DECISION" in i["title"].upper()]
    filters = {
        "agents": sorted({i["assignee"] for i in items}),
        "vps": sorted({i["vps"] for i in items}),
        "applications": sorted({i["application"] for i in items}),
        "activity_types": sorted({i["activity_type"] for i in items}),
        "statuses": sorted({i["status"] for i in items}),
        "priority_buckets": sorted({i["priority_bucket"] for i in items}),
    }
    return {
        "schema": SCHEMA,
        "generated_at": _now_iso(),
        "source": {"kanban": "Hermes Kanban local", "registry": "OA agent registry"},
        "mode": "dynamic-readonly-redacted",
        "window_days": window_days,
        "summary": {
            "tasks": len(items),
            "active": len(active_items),
            "blocked": by_status.get("blocked", 0),
            "done": by_status.get("done", 0),
            "agents": len(agents),
            "decision_required": len(decision_required),
            "by_status": dict(by_status),
            "by_priority": dict(by_priority),
            "by_vps": dict(by_vps),
            "by_type": dict(by_type),
        },
        "filters": filters,
        "agents": agents,
        "active_items": active_items[:80],
        "decision_required": decision_required[:40],
        "items": items[:limit],
        "errors": errors,
    }


if __name__ == "__main__":
    print(json.dumps(collect(), ensure_ascii=False, indent=2))
