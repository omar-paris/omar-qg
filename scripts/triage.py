#!/usr/bin/env python3
"""qg-triage — classe les issues ouvertes des repos CORE OA en P0/P1/P2.

Boucle d'auto-amélioration OA (validée Alex 10 juin 2026) :
  collecte (build.py 30 min) -> triage (ici, 1x/jour) -> digest H-Omar -> décision Alex.

Sortie : var/triage.json (republiée par build.py dans public/api/triage.json).
Le champ `next` de chaque app dans core-repos.json devient l'issue prioritaire
calculée ici — plus de prose codée en dur.

Règles (déterministes, auditables) puis raffinement LLM optionnel (--llm),
borné et avec fallback : si claude échoue, le classement règles fait foi.
Garde-fou v1 : cet agent ne ferme ni ne labellise rien — il propose.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VAR = ROOT / "var"
OUT = VAR / "triage.json"

REPOS = {
    "app":       "omar-paris/omar-app",
    "landing":   "omar-paris/omar-landing",
    "hub":       "omar-paris/omar-hub",
    "qg":        "omar-paris/omar-qg",
    "top":       "omar-paris/omar-top",
    "catalogue": "omar-paris/omar-catalogue",
}

# Règles écrites — l'ordre des familles fixe la priorité.
P0_PAT = re.compile(
    r"s[ée]curit|security|auth|pii|secret|token|vuln|leak|fuite|rgpd|"
    r"data.?loss|perte de donn|public sans|sans auth|down\b|critical|critique",
    re.IGNORECASE,
)
P1_PAT = re.compile(
    r"client|jab|bouboutou|maryse|lead|email|facture|paiement|payment|"
    r"onboarding|prod\b|bloqu|blocking|backup|sauvegarde",
    re.IGNORECASE,
)
P0_LABELS = {"security", "p0", "critical", "urgent"}
P1_LABELS = {"bug", "p1", "client", "ops"}


def gh_issues(slug: str) -> list[dict] | None:
    """3 tentatives avec backoff. None = échec (à distinguer de « 0 issue ») —
    jamais de troncature silencieuse : un échec doit se voir, pas ressembler à zéro."""
    for attempt in range(3):
        try:
            raw = subprocess.run(
                ["gh", "issue", "list", "--repo", slug, "--state", "open",
                 "--json", "number,title,labels,updatedAt", "--limit", "200"],
                capture_output=True, text=True, timeout=60,
            )
            if raw.returncode == 0:
                return json.loads(raw.stdout or "[]")
        except Exception:
            pass
        time.sleep(5 * (attempt + 1))
    return None


def score(issue: dict) -> str:
    labels = {l.get("name", "").lower() for l in issue.get("labels", [])}
    text = issue.get("title", "")
    if labels & P0_LABELS or P0_PAT.search(text):
        return "P0"
    if labels & P1_LABELS or P1_PAT.search(text):
        return "P1"
    return "P2"


def llm_refine(apps: dict) -> tuple[dict, bool]:
    """Demande à claude -p de revoir le classement règles. Borné, fallback total."""
    compact = []
    for app_id, data in apps.items():
        for it in data["top"]:
            compact.append(f'{app_id}#{it["number"]} [{it["prio"]}] {it["title"]}')
    if not compact:
        return apps, False
    prompt = (
        "Tu es l'agent de triage QG d'Omar & Alex (agence : assistant IA paperasse/marketing "
        "pour artisans ; clients actuels : JAB avocat, Maryse boulangère ; priorité = sécurité "
        "puis valeur client visible puis bloquants internes). Voici des issues classées par "
        "règles. Réponds UNIQUEMENT un objet JSON {\"app#num\": \"P0|P1|P2\"} pour les seules "
        "issues dont tu changerais la priorité (max 15). Issues :\n" + "\n".join(compact[:120])
    )
    try:
        r = subprocess.run(
            ["claude", "-p", prompt, "--model", "claude-sonnet-4-6"],
            capture_output=True, text=True, timeout=240,
        )
        m = re.search(r"\{[^{}]*\}", r.stdout, re.DOTALL)
        if r.returncode != 0 or not m:
            return apps, False
        overrides = json.loads(m.group(0))
        n = 0
        for key, prio in overrides.items():
            if prio not in ("P0", "P1", "P2") or "#" not in str(key):
                continue
            app_id, num = str(key).split("#", 1)
            for it in apps.get(app_id, {}).get("top", []):
                if str(it["number"]) == num.strip():
                    it["prio"], it["llm_adjusted"] = prio, True
                    n += 1
        return apps, n > 0
    except Exception:
        return apps, False


def main() -> None:
    use_llm = "--llm" in sys.argv
    previous = {}
    try:
        previous = json.loads(OUT.read_text(encoding="utf-8")).get("apps", {})
    except Exception:
        pass
    fetch_errors: list[str] = []
    apps: dict = {}
    for app_id, slug in REPOS.items():
        issues = gh_issues(slug)
        if issues is None:
            # Échec gh : on garde les données du run précédent, marquées stale
            fetch_errors.append(app_id)
            stale = dict(previous.get(app_id) or {"p0": 0, "p1": 0, "p2": 0, "top": []})
            stale["stale"] = True
            apps[app_id] = stale
            continue
        scored = [
            {"number": i["number"], "title": i["title"], "prio": score(i),
             "url": f"https://github.com/{slug}/issues/{i['number']}"}
            for i in issues
        ]
        scored.sort(key=lambda x: ({"P0": 0, "P1": 1, "P2": 2}[x["prio"]], -x["number"]))
        apps[app_id] = {
            "p0": sum(1 for s in scored if s["prio"] == "P0"),
            "p1": sum(1 for s in scored if s["prio"] == "P1"),
            "p2": sum(1 for s in scored if s["prio"] == "P2"),
            "top": scored[:10],
        }

    llm_used = False
    if use_llm:
        apps, llm_used = llm_refine(apps)
        for d in apps.values():  # re-trier après ajustements
            d["top"].sort(key=lambda x: ({"P0": 0, "P1": 1, "P2": 2}[x["prio"]], -x["number"]))
            d["p0"] = sum(1 for s in d["top"] if s["prio"] == "P0")

    for app_id, d in apps.items():
        d["next"] = (
            f'{d["top"][0]["prio"]} · #{d["top"][0]["number"]} — {d["top"][0]["title"]}'
            if d["top"] else "Rien d'ouvert — RAS."
        )
        if d.get("stale"):
            d["next"] = "⚠ données du run précédent (gh en échec) · " + d["next"]

    every = [dict(it, app=a) for a, d in apps.items() for it in d["top"]]
    every.sort(key=lambda x: ({"P0": 0, "P1": 1, "P2": 2}[x["prio"]], -x["number"]))
    out = {
        "built_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "llm_used": llm_used,
        "fetch_errors": fetch_errors,
        "apps": apps,
        "top3": every[:3],
    }
    VAR.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    total = sum(d["p0"] + d["p1"] + d["p2"] for d in apps.values())
    err = f" · ÉCHECS GH: {fetch_errors}" if fetch_errors else ""
    print(f"triage: {total} issues · top3={[t['app'] + '#' + str(t['number']) for t in out['top3']]} · llm={llm_used}{err}")


if __name__ == "__main__":
    main()
