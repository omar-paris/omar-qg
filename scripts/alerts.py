#!/usr/bin/env python3
"""oa-alerts — les apps en mode read (Hub/QG) remontent leurs pannes TOUTES SEULES.

Demande Alex 10 juin : « si à chaque fois que je regarde une app, je dois te dire
qu'elle ne marche plus, ça ne va pas. »
Règles : on n'alerte que les ANOMALIES NOUVELLES (état mémorisé), chaque alerte =
1 carte Kanban idempotente (assignee default = h-omar) + 1 Telegram. Disparition
de l'anomalie → la carte est complétée automatiquement.
"""
from __future__ import annotations
import json
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / "var" / "alerts-state.json"
TELEGRAM = Path.home() / "omar-alex-vps/scripts/send-telegram.sh"
HERMES = Path.home() / ".local/bin/hermes"


def collect() -> dict[str, str]:
    """anomalie_id -> description. Sources : core-repos.json, triage.json, vps.json."""
    a: dict[str, str] = {}
    try:
        core = json.loads((ROOT / "public/api/core-repos.json").read_text())
        for it in core.get("items", []):
            if it.get("health", {}).get("status") != "ok":
                a[f"health-{it['id']}"] = f"{it['domain']} ne répond pas (health {it['health'].get('http_code')})"
        if not core.get("fleet"):
            a["fleet-vide"] = "Flotte Hetzner illisible (vault ou API) — /clients/ affiche 'clef absente'"
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
    # OpenRouter n'est plus un signal bloquant OA: les agents routent via Codex + Nous/Nemotron.
    # Ne pas créer de carte “agents muets” sur solde OpenRouter seul.
    return a


def main() -> None:
    prev = {}
    try:
        prev = json.loads(STATE.read_text())
    except Exception:
        pass
    cur = collect()
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
    STATE.write_text(json.dumps(cur, ensure_ascii=False, indent=2))
    print(f"alerts: {len(cur)} actives · {len(new)} nouvelles · {len(gone)} résolues")


if __name__ == "__main__":
    main()
