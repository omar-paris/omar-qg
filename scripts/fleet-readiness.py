#!/usr/bin/env python3
"""fleet-readiness — matrice QG : Hermès + Hub + canal de communication par VPS.

Le QG est le SEUL endroit où vit l'inter-VPS (règle Alex). Cette matrice répond à
« vérifier que Hermès et le Hub sont installés sur les 3 VPS, maîtrisé depuis le QG ».

Contrat : le QG n'atteint PAS les VPS clients en direct. Omar est mesuré en local ;
Pantheos/JAB restent à confirmer par l'artefact QUE CHAQUE VPS EXPÉDIE (ship-own).
Le canal pour le leur demander = le kanban (carte à l'orchestrateur du VPS).
"""
from __future__ import annotations

import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

OT = Path("/home/omar/23-Offre/actifs/omar-top")
OUT = Path(__file__).resolve().parents[1] / "public" / "api" / "fleet-readiness.json"


def omar_conformity() -> str:
    runs = OT / "state" / "compliance" / "omar" / "runs.jsonl"
    if runs.exists():
        lines = [l for l in runs.read_text().splitlines() if l.strip()]
        if lines:
            return json.loads(lines[-1]).get("vps_grade", "indeterminate")
    return "indeterminate"


def omar_hermes() -> bool:
    if shutil.which("hermes"):
        return True
    return any(Path(p).exists() for p in (
        "/home/omar/.local/bin/hermes",
        "/mnt/HC_Volume_105618057/oa-offload-home-cache/.local/bin/hermes"))


def omar_hub() -> str:
    try:
        r = subprocess.run(["curl", "-sS", "-m", "5", "-o", "/dev/null",
                            "-w", "%{http_code}", "https://hub.omar.paris/"],
                           capture_output=True, text=True, timeout=8)
        return "installe" if r.stdout.strip() == "200" else "ko"
    except Exception:
        return "indeterminate"


FLEET = [
    {
        "vps": "omar", "role": "hôte / orchestrateur OA", "base_domain": "omar.paris",
        "orchestrateur": "default (H-Omar)", "canal": "kanban:default",
        "hermes": "installe" if omar_hermes() else "absent",
        "hub": omar_hub(),
        "conformite": omar_conformity(),
        "source": "mesuré en local",
    },
    {
        "vps": "pantheos", "role": "infra famille/édition (Aurel)", "base_domain": "pantheos.fr",
        "orchestrateur": "h-aurel", "canal": "kanban:h-aurel",
        "hermes": "absent (recon 10/07 — à confirmer par artefact expédié)",
        "hub": "absent (à installer)",
        "conformite": "red (recon)",
        "source": "recon provisoire — DOIT être remplacé par artefact ship-own",
    },
    {
        "vps": "jab", "role": "client (cabinet JAB)", "base_domain": "—",
        "orchestrateur": "cc-jab / edilia", "canal": "kanban:cc-jab",
        "hermes": "indeterminate (prod client — jamais lu depuis le QG)",
        "hub": "indeterminate",
        "conformite": "indeterminate",
        "source": "attend l'artefact expédié par JAB (ship-own)",
    },
]


def main() -> int:
    art = {
        "_meta": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "contract": "QG inter-VPS. Omar mesuré; clients indeterminate jusqu'à artefact ship-own. Canal = kanban.",
        },
        "convergence_cible": ["hermes-agent", "hub-local", "reporting", "observabilite"],
        "fleet": FLEET,
        "gaps": [f"{v['vps']}: hermes={v['hermes'].split(' ')[0]}, hub={v['hub'].split(' ')[0]}"
                 for v in FLEET if v["vps"] != "omar"],
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(art, ensure_ascii=False, indent=2))
    # affichage matrice
    print(f"{'VPS':10} {'Hermès':12} {'Hub':12} {'Conformité':14} {'Canal':16}")
    print("-" * 66)
    for v in FLEET:
        print(f"{v['vps']:10} {v['hermes'].split(' ')[0]:12} {v['hub'].split(' ')[0]:12} "
              f"{v['conformite'].split(' ')[0]:14} {v['canal']:16}")
    print(f"\n-> {OUT.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
