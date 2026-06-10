#!/usr/bin/env python3
"""vps-doctor — état des 3 VPS OA contre le standard VPS Hermes OA (OmarTop).

Sortie : var/vps.json (republiée par build.py dans public/api/vps.json).
V1 : VPS-Omar mesuré (oa-doctor + santé système) ; JAB et Pantheos en pending
(JAB = couloir agent JAB, Pantheos = install OA-L1 post-META ~22 juin).
Leçon du 9 juin (OOM hermes-gateway) : surveille orphelins claude + swap.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "var" / "vps.json"
OA_DOCTOR = Path("/home/omar/23-Offre/actifs/omar-top/bin/oa-doctor")

SERVICES_SYSTEM = ["caddy", "docker", "tailscaled"]
SERVICES_USER = ["hermes-gateway", "openclaw-gateway", "oa-proposal-server"]


def run(cmd: list[str], timeout: int = 30) -> str:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip()
    except Exception:
        return ""


def oa_doctor() -> dict:
    """Parse la sortie JSONL d'oa-doctor (un objet JSON par phase P0→P6)."""
    if not OA_DOCTOR.exists():
        return {"available": False}
    out = run([str(OA_DOCTOR), "--check-phase", "all", "--json"], timeout=120)
    phases, ok, ko, skip = [], 0, 0, 0
    for line in out.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            p = json.loads(line)
        except Exception:
            continue
        phases.append({"phase": p.get("phase"), "name": p.get("name"),
                       "pass": p.get("pass", 0), "fail": p.get("fail", 0), "skip": p.get("skip", 0)})
        ok += p.get("pass", 0)
        ko += p.get("fail", 0)
        skip += p.get("skip", 0)
    if not phases:
        return {"available": True, "parse_error": True, "raw_text": out[:2000]}
    measured = ok + ko  # les SKIP (standards client non applicables ici) sont hors score
    return {"available": True, "pass": ok, "fail": ko, "skip": skip,
            "total": measured, "score_pct": round(100 * ok / measured) if measured else None,
            "phases": phases}


def system_health() -> dict:
    disk = run(["df", "--output=pcent", "/"]).splitlines()
    swap_line = [l for l in run(["free", "-m"]).splitlines() if l.startswith("Swap")]
    swap_pct = None
    if swap_line:
        parts = swap_line[0].split()
        if len(parts) >= 3 and int(parts[1]) > 0:
            swap_pct = round(100 * int(parts[2]) / int(parts[1]))
    orphans = run(["bash", "-c", "ps aux | grep 'native-binary/claude' | grep -v grep | wc -l"])
    services = {}
    for s in SERVICES_SYSTEM:
        if shutil.which("systemctl"):
            services[s] = run(["systemctl", "is-active", s]) or "unknown"
    for s in SERVICES_USER:
        services[s + " (user)"] = run(["systemctl", "--user", "is-active", s]) or "unknown"
    alerts = []
    if swap_pct is not None and swap_pct > 80:
        alerts.append(f"swap {swap_pct}% (>80) — risque OOM, cf. incident 9 juin")
    try:
        if int(orphans or 0) > 5:
            alerts.append(f"{orphans} processus claude orphelins (>5)")
    except ValueError:
        pass
    for name, state in services.items():
        if state not in ("active", "unknown"):
            alerts.append(f"service {name}: {state}")
    return {
        "disk_root": disk[-1].strip() if len(disk) > 1 else None,
        "swap_pct": swap_pct,
        "claude_orphans": int(orphans) if (orphans or "").isdigit() else None,
        "services": services,
        "alerts": alerts,
    }


def pantheos_remote() -> dict:
    """Mesure read-only de VPS-Pantheos via SSH tailnet (pré-install OA-L1)."""
    base = {"id": "vps-pantheos", "name": "VPS-Pantheos (perso Alex)"}
    script = (
        "df --output=pcent / | tail -1; "
        "free -m | awk '/^Swap/{print ($2>0)? int(100*$3/$2) : -1}'; "
        "for s in nginx docker tailscaled; do systemctl is-active $s; done; "
        "systemctl is-active openclaw-gateway pantheos-os 2>/dev/null | tr '\\n' ' '; echo; "
        "test -d ~/.hermes && echo hermes-present || echo hermes-absent"
    )
    out = run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8",
               "aurel@vps-pantheos", script], timeout=30)
    lines = [l.strip() for l in out.splitlines() if l.strip()]
    if len(lines) < 5:
        return {**base, "status": "pending",
                "note": "SSH indisponible — install OA-L1 post-META (~22 juin)."}
    disk, swap = lines[0], lines[1]
    services = {"nginx": lines[2], "docker": lines[3], "tailscaled": lines[4]}
    hermes = "present" if "hermes-present" in out else "absent"
    alerts = []
    if swap == "-1":
        alerts.append("aucun swap configuré — risque OOM (cf. incident VPS-Omar 9 juin)")
    try:
        if int(disk.strip().rstrip("%")) > 70:
            alerts.append(f"disque {disk.strip()} (>70%)")
    except ValueError:
        pass
    if hermes == "absent":
        alerts.append("Hermes runtime absent — install prévue avec OA-L1")
    for name, state in services.items():
        if state != "active":
            alerts.append(f"service {name}: {state}")
    return {**base, "status": "measured (read-only, pré-install)",
            "doctor": {"available": False, "note": "oa-doctor sera installé avec OA-L1 (~22 juin)"},
            "system": {"disk_root": disk.strip(), "swap_pct": None if swap == "-1" else int(swap),
                       "hermes": hermes, "services": services, "alerts": alerts}}


def main() -> None:
    omar = {
        "id": "vps-omar",
        "name": "VPS-Omar (amiral, CORE OA)",
        "status": "measured",
        "doctor": oa_doctor(),
        "system": system_health(),
    }
    out = {
        "built_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "standard": "VPS Hermes OA (OmarTop phases-spec P0→P6)",
        "vps": [
            omar,
            {"id": "vps-jab", "name": "VPS-JAB (Bouboutou)", "status": "pending",
             "note": "Branchement QG read-only via tailnet — couloir agent JAB (qg#15)."},
            pantheos_remote(),
        ],
    }
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    a = omar["system"]["alerts"]
    print(f"vps-doctor: omar mesuré · alerts={a or 'aucune'} · jab/pantheos pending")


if __name__ == "__main__":
    main()
