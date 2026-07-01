#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = Path("/home/omar/11-Pilotage/sujets-actifs/oa-os/tool-eval-capability-registry/2026-07-01-tool-eval-capability-registry.json")
PUBLIC_API = ROOT / "public" / "api"
SCHEMA = "oa.capabilities-eval/1"
STALE_AFTER_HOURS = 48
STATUS_KEYS = ("installed", "reachable", "integrated", "used", "measured")


def _parse_dt(value: str | None) -> dt.datetime | None:
    if not value:
        return None
    try:
        return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _count_statuses(capabilities: list[dict[str, Any]]) -> dict[str, int]:
    counts = {key: 0 for key in STATUS_KEYS}
    for cap in capabilities:
        statuses = set(map(str, cap.get("status") or []))
        for key in STATUS_KEYS:
            if key in statuses:
                counts[key] += 1
    return counts


def _safe_gap(gap: dict[str, Any]) -> dict[str, Any]:
    return {
        "rank": gap.get("rank"),
        "area": str(gap.get("area") or "unknown"),
        "gap": str(gap.get("gap") or ""),
        "impact": str(gap.get("impact") or ""),
        "short_fix": str(gap.get("short_fix") or ""),
    }


def _capability_ids_from_gaps(top_gaps: list[dict[str, Any]], capabilities: list[dict[str, Any]]) -> list[str]:
    ids_by_text = {
        "langfuse": ["langfuse", "litellm"],
        "litellm": ["langfuse", "litellm"],
        "capability context": ["agent-registry", "hermes-default", "qg-static-api"],
        "qg cockpit": ["qg-hermesui", "qg-static-api", "agent-registry"],
        "kanban": ["kanban", "profiles"],
        "github": ["github-cli", "github-actions"],
        "cron": ["cron", "scripts"],
        "nango": ["nango"],
        "vault": ["vault"],
        "ollama": ["ollama"],
    }
    existing = {str(cap.get("id")) for cap in capabilities}
    ordered: list[str] = []
    for gap in top_gaps:
        text = f"{gap.get('area', '')} {gap.get('gap', '')}".lower()
        for needle, ids in ids_by_text.items():
            if needle in text:
                for cid in ids:
                    if cid in existing and cid not in ordered:
                        ordered.append(cid)
    return ordered[:8]


def _agent_context_contract(recommended_ids: list[str]) -> dict[str, Any]:
    return {
        "field": "capability_context_ids",
        "principle": "Injecter uniquement les capacités nécessaires à la mission, jamais tout le registry.",
        "selection_rules": [
            "Partir du contrat de mission: domaine, outils requis, preuves attendues.",
            "Sélectionner 3 à 8 ids maximum, liés aux preuves ou aux risques de la mission.",
            "Inclure qg-static-api quand la mission doit publier un artefact QG.",
            "Inclure agent-registry quand la mission doit choisir ou vérifier des capacités.",
            "Ne jamais injecter evidence brute contenant sorties de commandes, tokens, chemins secrets ou données client non requises.",
        ],
        "allowed_fields_per_capability": ["id", "name", "type", "status", "owner", "known_gaps", "how_to_use", "proof_command", "security_scope", "last_checked"],
        "recommended_initial_ids": recommended_ids,
        "example": {"mission": "Publier le résumé capability-eval dans QG", "capability_context_ids": ["qg-static-api", "qg-hermesui", "agent-registry"]},
    }


def collect(source: Path = DEFAULT_SOURCE, now: dt.datetime | None = None) -> dict[str, Any]:
    now = now or dt.datetime.now(dt.timezone.utc)
    if not source.exists():
        return {"schema": SCHEMA, "generated_at": now.isoformat(), "source": str(source), "source_generated_at": None, "stale": True, "stale_after_hours": STALE_AFTER_HOURS, "status": "missing_source", "counts": {key: 0 for key in STATUS_KEYS}, "capabilities_total": 0, "top_gaps": [], "next_action": "Regénérer le registre capability-eval source puis relancer le build QG.", "agent_context_contract": _agent_context_contract([])}
    raw = json.loads(source.read_text(encoding="utf-8"))
    capabilities = raw.get("capabilities") if isinstance(raw.get("capabilities"), list) else []
    top_gaps_raw = raw.get("top_10_gaps") if isinstance(raw.get("top_10_gaps"), list) else []
    top_gaps = [_safe_gap(g) for g in top_gaps_raw[:5] if isinstance(g, dict)]
    source_generated_at = str(raw.get("generated_at") or "")
    source_dt = _parse_dt(source_generated_at)
    if source_dt and source_dt.tzinfo is None:
        source_dt = source_dt.replace(tzinfo=dt.timezone.utc)
    source_dt = source_dt.astimezone(dt.timezone.utc) if source_dt else None
    age_hours = None
    stale = True
    if source_dt is not None:
        age_hours = round((now.astimezone(dt.timezone.utc) - source_dt).total_seconds() / 3600, 2)
        stale = age_hours > STALE_AFTER_HOURS
    summary = raw.get("summary") if isinstance(raw.get("summary"), dict) else {}
    next_action = str(summary.get("next_action") or "") if summary else ""
    if not next_action and top_gaps:
        next_action = top_gaps[0].get("short_fix", "")
    ids = _capability_ids_from_gaps(top_gaps, capabilities)
    return {"schema": SCHEMA, "generated_at": now.isoformat(), "source": str(source), "source_generated_at": source_generated_at or None, "source_task_id": raw.get("task_id"), "stale": stale, "age_hours": age_hours, "stale_after_hours": STALE_AFTER_HOURS, "status": "stale" if stale else "fresh", "counts": _count_statuses(capabilities), "capabilities_total": len(capabilities), "top_gaps": top_gaps, "next_action": next_action, "agent_context_contract": _agent_context_contract(ids)}


def render_markdown(payload: dict[str, Any]) -> str:
    counts = payload.get("counts", {}) or {}
    lines = ["# QG capability eval summary", f"- schema: {payload.get('schema')}", f"- generated_at: {payload.get('generated_at')}", f"- source_generated_at: {payload.get('source_generated_at')}", f"- status: {payload.get('status')} (stale={str(payload.get('stale')).lower()}, age_hours={payload.get('age_hours')})", f"- capabilities_total: {payload.get('capabilities_total')}", "", "## Counts"]
    for key in STATUS_KEYS:
        lines.append(f"- {key}: {counts.get(key, 0)}")
    lines.extend(["", "## Top gaps"])
    for gap in payload.get("top_gaps", []) or []:
        lines.append(f"{gap.get('rank')}. {gap.get('area')} — {gap.get('gap')}")
        if gap.get("short_fix"):
            lines.append(f"   - next: {gap.get('short_fix')}")
    contract = payload.get("agent_context_contract") or {}
    lines.extend(["", "## Next action", str(payload.get("next_action") or ""), "", "## Agent context contract", "Agents doivent demander un champ `capability_context_ids` filtré (3 à 8 ids max) et recevoir uniquement les champs non sensibles autorisés par capacité.", f"- recommended_initial_ids: {', '.join(contract.get('recommended_initial_ids') or [])}", "- allowed_fields: " + ", ".join(contract.get("allowed_fields_per_capability") or [])])
    return "\n".join(lines).rstrip() + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", default=str(DEFAULT_SOURCE))
    parser.add_argument("--write", action="store_true", help="write public/api/capabilities-eval.{json,md}")
    args = parser.parse_args()
    payload = collect(Path(args.source))
    if args.write:
        PUBLIC_API.mkdir(parents=True, exist_ok=True)
        (PUBLIC_API / "capabilities-eval.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        (PUBLIC_API / "capabilities-eval.md").write_text(render_markdown(payload), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
