#!/usr/bin/env python3
"""Read-only, redacted collector for oa.delivery-outcomes/v1."""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT_SOURCE = Path("/home/omar/11-Pilotage/ledgers/outcomes")
ALLOWED_PHASES = frozenset({
    "backlog", "implementation", "review", "integration", "deployed", "rodage", "maintenance", "unknown",
})
ALLOWED_ACTORS = frozenset({"alex", "cc-omar", "h-omar", "h-athena"})
MAX_ERRORS = 20
MAX_ITEMS = 200
MAX_TEXT = 500
_SAFE_REF = re.compile(r"^(?:[A-Za-z][A-Za-z0-9_.-]*:)?[A-Za-z0-9][A-Za-z0-9_.#:/@-]{0,240}$")
_FORBIDDEN_TEXT = ("authorization:", "begin openssh", "begin private", "ghp_", "sk-", "/home/", "~/.hermes", ".env")


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _safe_text(value: Any, limit: int = MAX_TEXT) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = " ".join(value.strip().split())
    if not normalized or len(normalized) > limit:
        return None
    if any(marker in normalized.lower() for marker in _FORBIDDEN_TEXT):
        return None
    return normalized


def _safe_ref(value: Any) -> str | None:
    text = _safe_text(value, limit=260)
    return text if text and _SAFE_REF.fullmatch(text) else None


def _safe_refs(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [ref for ref in (_safe_ref(item) for item in value[:20]) if ref]


def _safe_record(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    summary = _safe_text(value.get("summary"))
    if not summary:
        return None
    record: dict[str, Any] = {"summary": summary}
    refs = _safe_refs(value.get("evidence_refs", []))
    if refs:
        record["evidence_refs"] = refs
    return record


def _safe_records(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [record for record in (_safe_record(item) for item in value[:50]) if record]


def _unknown_item(outcome_id: str = "unknown", project_id: str = "unknown") -> dict[str, Any]:
    return {
        "outcome_id": outcome_id if _safe_ref(outcome_id) else "unknown",
        "project_id": project_id if _safe_ref(project_id) else "unknown",
        "title": "Outcome unavailable",
        "phase": "unknown",
        "status": "unknown",
        "responsible_now": "unknown",
        "updated_at": None,
        "next_gate": "unknown",
        "feedbacks": [],
        "delivery": {"decisions": [], "implementation": [], "reviews": [], "tests": [], "live_proofs": []},
        "anomalies": ["source_invalid"],
    }


def normalize_outcome(raw: Any) -> tuple[dict[str, Any], str | None]:
    if not isinstance(raw, dict):
        return _unknown_item(), "not_object"
    outcome_id = raw.get("outcome_id")
    project_id = raw.get("project_id")
    required_text = ("outcome_id", "project_id", "title", "status", "responsible_now", "updated_at", "next_gate")
    if any(_safe_text(raw.get(field)) is None for field in required_text):
        return _unknown_item(str(outcome_id or "unknown"), str(project_id or "unknown")), "missing_required"
    phase = raw.get("phase")
    if phase not in ALLOWED_PHASES:
        return _unknown_item(str(outcome_id), str(project_id)), "invalid_phase"

    feedbacks = []
    for feedback in raw.get("feedbacks", []) if isinstance(raw.get("feedbacks"), list) else []:
        if not isinstance(feedback, dict) or feedback.get("actor") not in ALLOWED_ACTORS:
            continue
        kind = _safe_text(feedback.get("kind"), 80)
        summary = _safe_text(feedback.get("summary"))
        disposition = _safe_text(feedback.get("disposition"), 80)
        if not (kind and summary and disposition):
            continue
        feedbacks.append({
            "actor": feedback["actor"], "kind": kind, "summary": summary,
            "disposition": disposition, "evidence_refs": _safe_refs(feedback.get("evidence_refs", [])),
        })

    delivery_raw = raw.get("delivery") if isinstance(raw.get("delivery"), dict) else {}
    delivery = {key: _safe_records(delivery_raw.get(key, [])) for key in ("decisions", "implementation", "reviews", "tests", "live_proofs")}
    raw_anomalies = raw.get("anomalies")
    anomalies = [_safe_text(item, 200) for item in raw_anomalies[:30] if _safe_text(item, 200)] if isinstance(raw_anomalies, list) else []
    return {
        "outcome_id": _safe_text(outcome_id, 160),
        "project_id": _safe_text(project_id, 160),
        "title": _safe_text(raw["title"]),
        "phase": phase,
        "status": _safe_text(raw["status"], 80),
        "responsible_now": _safe_text(raw["responsible_now"], 120),
        "updated_at": _safe_text(raw["updated_at"], 80),
        "next_gate": _safe_text(raw["next_gate"]),
        "feedbacks": feedbacks,
        "delivery": delivery,
        "anomalies": anomalies,
    }, None


def collect(source_dir: Path | None = None) -> dict[str, Any]:
    source_dir = source_dir or Path(os.environ.get("OA_DELIVERY_OUTCOMES_SOURCE", str(DEFAULT_SOURCE)))
    errors: list[str] = []
    items: list[dict[str, Any]] = []
    if not source_dir.is_dir():
        return {"schema": "oa.delivery-outcomes/v1", "status": "unknown", "generated_at": _now(), "source": "append-only outcome reports", "summary": {"total": 0, "unknown": 0}, "items": [], "errors": ["source_missing"]}

    for path in sorted(source_dir.glob("*.json"))[:MAX_ITEMS]:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            if len(errors) < MAX_ERRORS:
                errors.append(f"invalid:{path.name}:json")
            items.append(_unknown_item())
            continue
        records = raw if isinstance(raw, list) else [raw]
        for record in records[:MAX_ITEMS - len(items)]:
            normalized, error = normalize_outcome(record)
            items.append(normalized)
            if error and len(errors) < MAX_ERRORS:
                errors.append(f"invalid:{path.name}:{error}")

    unknown = sum(1 for item in items if item["phase"] == "unknown" or item["status"] == "unknown")
    status = "ok" if items and not errors else "unknown"
    return {
        "schema": "oa.delivery-outcomes/v1",
        "status": status,
        "generated_at": _now(),
        "source": "append-only outcome reports",
        "summary": {"total": len(items), "unknown": unknown},
        "items": items,
        "errors": errors,
    }


if __name__ == "__main__":
    print(json.dumps(collect(), ensure_ascii=False, indent=2))
