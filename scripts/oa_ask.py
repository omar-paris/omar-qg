#!/usr/bin/env python3
"""oa-ask — tout agent pose une question à Alex (boîte de décisions qg#27).

Unicité par hash(groupe+texte). Si --blocked t_xxx : bloque la carte kanban,
qui sera débloquée automatiquement par la réponse d'Alex sur /decisions/.

Usage :
  oa_ask.py --group pantheos-install --open "Quel périmètre pour H-Aurel ?" --context "..."
  oa_ask.py --group pantheos-install --closed "Quel bot Telegram ?" --options "dédié,openclaw" --blocked t_xxx
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path

STORE = Path(__file__).resolve().parents[1] / "var" / "decisions.json"


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--group", required=True)
    p.add_argument("--open", dest="open_q")
    p.add_argument("--closed", dest="closed_q")
    p.add_argument("--options", default="")
    p.add_argument("--context", default="")
    p.add_argument("--blocked", default="", help="t_xxx (carte kanban) ou repo#num (issue)")
    p.add_argument("--par", default="agent")
    a = p.parse_args()
    text = a.open_q or a.closed_q
    if not text:
        sys.exit("--open ou --closed requis")
    if a.closed_q and not a.options:
        sys.exit("--options requis pour une question fermée")
    qid = hashlib.sha1(f"{a.group}|{text}".encode()).hexdigest()[:10]
    items = []
    try:
        items = json.loads(STORE.read_text(encoding="utf-8"))
    except Exception:
        pass
    for q in items:
        if q["id"] == qid and q["statut"] == "ouverte":
            print(f"doublon — question déjà ouverte : {qid}")
            return
    items.append({
        "id": qid, "groupe": a.group, "type": "fermée" if a.closed_q else "ouverte",
        "texte": text, "options": [o.strip() for o in a.options.split(",") if o.strip()],
        "contexte": a.context, "blocked_ref": a.blocked, "posee_par": a.par,
        "posee_le": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "statut": "ouverte", "reponse": None,
    })
    STORE.parent.mkdir(exist_ok=True)
    payload = json.dumps(items, ensure_ascii=False, indent=2)
    STORE.write_text(payload, encoding="utf-8")
    # Reflet IMMÉDIAT dans la page servie (sinon lag jusqu'au rebuild 30 min — fix 14/06)
    pub = STORE.parent.parent / "public" / "api" / "decisions.json"
    try:
        if pub.parent.exists():
            pub.write_text(payload, encoding="utf-8")
    except Exception:
        pass
    if a.blocked.startswith("t_"):
        subprocess.run(["hermes", "kanban", "block", a.blocked, "--reason", f"decision:{qid}"],
                       capture_output=True, timeout=30)
    print(f"question {qid} ouverte (groupe {a.group})" + (f" — carte {a.blocked} bloquée" if a.blocked.startswith("t_") else ""))


if __name__ == "__main__":
    main()
