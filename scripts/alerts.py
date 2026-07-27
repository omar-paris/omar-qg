#!/usr/bin/env python3
"""oa-alerts — les apps en mode read (Hub/QG) remontent leurs pannes TOUTES SEULES.

Demande Alex 10 juin : « si à chaque fois que je regarde une app, je dois te dire
qu'elle ne marche plus, ça ne va pas. »
Règles : on n'alerte que les ANOMALIES NOUVELLES (état mémorisé), chaque alerte =
1 carte Kanban idempotente (assignee default = h-omar) + 1 Telegram. Disparition
de l'anomalie → la carte est complétée automatiquement.

QG-100 : dead-man's-switch inter-VPS. Si un VPS attendu ne heartbeat plus via
`oa.vps-report/v1`, l'alerte n'est activée qu'après 2 cycles consécutifs
(flap-damping simple). Le dead-man mesure uniquement un heartbeat natif/source
ou un transport réellement reçu, jamais un timestamp synthétique réécrit par le
QG pendant la normalisation locale.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / "var" / "alerts-state.json"
DAMPING_STATE = ROOT / "var" / "alerts-damping-state.json"
TELEGRAM = Path.home() / "omar-alex-vps/scripts/send-telegram.sh"
HERMES = Path.home() / ".local/bin/hermes"

HEARTBEAT_SILENCE_MIN = int(os.environ.get("QG_VPS_HEARTBEAT_SILENCE_MIN", "4"))
DEADMAN_DAMPING_CYCLES = int(os.environ.get("QG_DEADMAN_DAMPING_CYCLES", "2"))
ALERTS_CRON_INTERVAL_MIN = int(os.environ.get("QG_ALERTS_CRON_INTERVAL_MIN", "5"))

INTER_VPS_REPORT_DIRS = [
    Path("/home/omar/11-Pilotage/sujets-actifs/inter-vps-inbox"),
    Path("/home/omar/11-Pilotage/sujets-actifs/fable-5-rails-1-2/inbox-from-pantheos"),
]
if os.environ.get("QG_USE_TEST_FIXTURES") == "1":
    INTER_VPS_REPORT_DIRS = [ROOT / "tests" / "fixtures" / "inter-vps-inbox"]

# Cadence par nœud : seuil = cadence réelle attendue + marge, sauf oa-master où
# QG-100 exige un reporter natif rapide. Ne pas forcer un seuil */5 à un nœud qui
# n'a pas encore de reporter natif */5, sinon le QG flappe mécaniquement.
DEADMAN_EXPECTED_NODES = [
    {
        "id": "oa-master",
        "aliases": {"oa-master", "omar", "vps-omar"},
        "label": "oa-master / VPS-Omar",
        "owner": "h-omar",
        "expected_path": "/home/omar/11-Pilotage/sujets-actifs/inter-vps-inbox/omar/vps-report-latest.json",
        "cadence": "native */5 required",
        "silence_min": HEARTBEAT_SILENCE_MIN,
    },
    {
        "id": "jab",
        "aliases": {"jab", "vps-jab"},
        "label": "jab / VPS-JAB",
        "owner": "cc-jab",
        "expected_path": "/home/omar/11-Pilotage/sujets-actifs/inter-vps-inbox/jab/vps-report-latest.json",
        "cadence": "daily 07:30 + 2h margin",
        "silence_min": 26 * 60,
    },
    {
        "id": "pantheos",
        "aliases": {"pantheos", "vps-pantheos"},
        "label": "pantheos",
        "owner": "h-aurel",
        "expected_path": "/home/omar/11-Pilotage/sujets-actifs/inter-vps-inbox/pantheos/vps-report-latest.json",
        "cadence": "pull every 30 min + one missed pull + 5 min margin",
        "silence_min": 65,
    },
]


def _now_utc() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _parse_ts(value) -> dt.datetime | None:
    try:
        parsed = dt.datetime.fromisoformat(str(value or "").strip().replace("Z", "+00:00"))
    except Exception:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=dt.timezone.utc)


def _inter_vps_report_paths(root: Path) -> list[Path]:
    paths = set(root.rglob("*health*.json"))
    paths.update(root.rglob("vps-report-latest.json"))
    paths.update(root.rglob("*vps-report*.json"))
    return sorted(paths)


def _report_ids(payload: dict, path: Path) -> set[str]:
    ids: set[str] = set()
    for key in ("node", "vps_id"):
        value = str(payload.get(key) or "").strip().lower()
        if value:
            ids.add(value)
            if value.startswith("vps-"):
                ids.add(value.removeprefix("vps-"))
    if path.name == "vps-report-latest.json" and path.parent.name:
        ids.add(path.parent.name.strip().lower())
    if not ids:
        ids.add(path.stem.split("-", 1)[0].strip().lower())
    return {i for i in ids if i}


def _native_heartbeat_value(report: dict):
    """Timestamp autorisé pour le dead-man.

    `source_report_generated_at` est le heartbeat natif quand un normaliseur QG a
    déjà réécrit `generated_at` localement. `generated_at` reste accepté seulement
    quand aucun champ source n'existe, c.-à-d. rapport natif non normalisé ou
    artefact transport reçu tel quel.
    """
    return report.get("source_report_generated_at") or report.get("generated_at")


def _normalize_received_report(payload: dict, path: Path) -> dict:
    normalized = dict(payload)
    native_generated_at = str(_native_heartbeat_value(normalized) or "unknown")
    local_generated_at = str(normalized.get("generated_at") or "unknown")
    # Si un collecteur local a utilisé generated_at comme horloge de normalisation,
    # on conserve explicitement les deux notions au lieu de laisser le dead-man les
    # confondre.
    if normalized.get("source_report_generated_at"):
        normalized.setdefault("observed_at", local_generated_at)
        normalized.setdefault("normalized_at", local_generated_at)
        normalized["generated_at"] = str(normalized.get("source_report_generated_at"))
    else:
        normalized.setdefault("source_report_generated_at", local_generated_at)
        normalized.setdefault("observed_at", str(normalized.get("observed_at") or "unknown"))
        normalized.setdefault("normalized_at", str(normalized.get("normalized_at") or "unknown"))
    normalized["_native_generated_at"] = native_generated_at
    normalized["_source_path"] = str(path)
    normalized["_ids"] = sorted(_report_ids(normalized, path))
    return normalized


def _read_inter_vps_reports() -> list[dict]:
    reports: list[dict] = []
    for root in INTER_VPS_REPORT_DIRS:
        if not root.exists():
            continue
        for path in _inter_vps_report_paths(root):
            if any(part in {"_invalid", "_validated", "archive"} for part in path.parts):
                continue
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if not isinstance(payload, dict) or payload.get("schema") != "oa.vps-report/v1":
                continue
            reports.append(_normalize_received_report(payload, path))
    return reports


def collect_vps_deadman(now: dt.datetime | None = None) -> dict[str, str]:
    """Retourne les VPS dont le heartbeat source oa.vps-report/v1 est absent/stale."""
    now = now or _now_utc()
    reports = _read_inter_vps_reports()
    out: dict[str, str] = {}
    for expected in DEADMAN_EXPECTED_NODES:
        silence_min = int(expected.get("silence_min", HEARTBEAT_SILENCE_MIN))
        aliases = {str(a).lower() for a in expected["aliases"]}
        candidates = [r for r in reports if aliases.intersection(set(r.get("_ids") or []))]
        latest = None
        latest_ts = None
        for report in candidates:
            ts = _parse_ts(report.get("_native_generated_at"))
            if ts is not None and (latest_ts is None or ts > latest_ts):
                latest = report
                latest_ts = ts
        key = f"deadman-vps-{expected['id']}"
        if latest is None or latest_ts is None:
            out[key] = (
                f"Dead-man's-switch: aucun source heartbeat {expected['label']} reçu "
                f"(seuil {silence_min} min, cadence {expected.get('cadence', 'unknown')}, "
                f"owner {expected['owner']}, attendu: {expected['expected_path']})"
            )
            continue
        age_exact_min = (now - latest_ts).total_seconds() / 60
        if age_exact_min >= silence_min:
            age_display_min = round(age_exact_min, 1)
            out[key] = (
                f"Dead-man's-switch: source heartbeat {expected['label']} stale depuis {age_display_min:g} min "
                f"(source generated_at {latest.get('_native_generated_at')}, observed_at {latest.get('observed_at')}, "
                f"normalized_at {latest.get('normalized_at')}, seuil {silence_min} min, "
                f"cadence {expected.get('cadence', 'unknown')}, owner {expected['owner']}, "
                f"source: {latest.get('_source_path')})"
            )
    return out


def _load_json_obj(path: Path) -> dict:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def apply_deadman_damping(raw: dict[str, str], previous: dict, now_ts: int | None = None) -> tuple[dict[str, str], dict]:
    """Active une alerte deadman seulement après N cycles consécutifs.

    Les autres alertes historiques restent immédiates. `previous` est le contenu
    de `alerts-damping-state.json` et le second retour est le prochain état.
    """
    now_ts = int(now_ts if now_ts is not None else time.time())
    tracked_prefix = "deadman-vps-"
    next_state: dict = {}
    damped: dict[str, str] = {}
    for key, desc in raw.items():
        if not key.startswith(tracked_prefix):
            damped[key] = desc
            continue
        raw_prev = previous.get(key)
        prev = raw_prev if isinstance(raw_prev, dict) else {}
        consecutive = int(prev.get("consecutive", 0)) + 1
        first_seen = int(prev.get("first_seen_at", now_ts))
        next_state[key] = {
            "consecutive": consecutive,
            "first_seen_at": first_seen,
            "last_seen_at": now_ts,
            "last_description": desc,
        }
        if consecutive >= DEADMAN_DAMPING_CYCLES:
            damped[key] = desc + f" · confirmé {consecutive} cycles consécutifs"
    return damped, next_state


def collect(*, damped: bool = True, now: dt.datetime | None = None) -> dict[str, str]:
    """anomalie_id -> description. Sources : core-repos.json, triage.json, vps.json, inter-VPS heartbeat."""
    a: dict[str, str] = {}
    try:
        core = json.loads((ROOT / "public/api/core-repos.json").read_text())
        for it in core.get("items", []):
            if it.get("health", {}).get("status") != "ok":
                a[f"health-{it['id']}"] = f"{it['domain']} ne répond pas (health {it['health'].get('http_code')})"
        fleet_status = core.get("fleet_status", "unknown")
        if fleet_status in {"vault_unavailable", "api_error"}:
            a["fleet-vault-unavailable"] = f"Flotte Hetzner non rafraîchie ({fleet_status})"
        elif not core.get("fleet"):
            a["fleet-vide"] = "Flotte Hetzner vide ou secret absent"
    except Exception:
        a["core-repos-illisible"] = "core-repos.json illisible — le build QG est cassé"
    try:
        tri = json.loads((ROOT / "var/triage.json").read_text())
        for app in tri.get("fetch_errors", []):
            a[f"triage-gh-{app}"] = f"triage : gh en échec pour {app} (données stale)"
    except Exception:
        pass
    try:
        vps = json.loads((ROOT / "var/vps.json").read_text())
        for v in vps.get("vps", []):
            for al in (v.get("system") or {}).get("alerts", []):
                if "Hermes runtime absent" in al or "install prévue" in al:
                    continue  # état connu pré-install, pas une panne
                a[f"vps-{v['id']}-{al[:24]}"] = f"{v['id']} : {al}"
    except Exception:
        pass
    a.update(collect_vps_deadman(now=now))
    # OpenRouter n'est plus un signal bloquant OA: les agents routent via Codex + Nous/Nemotron.
    # Ne pas créer de carte “agents muets” sur solde OpenRouter seul.
    if not damped:
        return a
    cur, next_state = apply_deadman_damping(a, _load_json_obj(DAMPING_STATE))
    DAMPING_STATE.parent.mkdir(parents=True, exist_ok=True)
    DAMPING_STATE.write_text(json.dumps(next_state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return cur


def main() -> None:
    prev = _load_json_obj(STATE)
    cur = collect(damped=True)
    new = {k: v for k, v in cur.items() if k not in prev}
    gone = {k: v for k, v in prev.items() if k not in cur}
    for key, desc in new.items():
        subprocess.run([str(HERMES), "kanban", "create", f"ALERTE: {desc[:70]}",
                        "--assignee", "default", "--priority", "90",
                        "--idempotency-key", f"alert-{key}",
                        "--body", f"Alerte automatique oa-alerts ({time.strftime('%Y-%m-%d %H:%M')}).\n\n{desc}\n\nDiagnostiquer, réparer si runbook connu, sinon escalader (boîte de décisions)."],
                       capture_output=True, timeout=30)
        if TELEGRAM.exists():
            subprocess.run([str(TELEGRAM), f"🔴 QG ALERTE : {desc}"], capture_output=True, timeout=20)
    for key in gone:
        if TELEGRAM.exists():
            subprocess.run([str(TELEGRAM), f"🟢 résolu : {prev[key]}"], capture_output=True, timeout=20)
    STATE.write_text(json.dumps(cur, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"alerts: {len(cur)} actives · {len(new)} nouvelles · {len(gone)} résolues")


if __name__ == "__main__":
    main()
