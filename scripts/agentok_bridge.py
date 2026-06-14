#!/usr/bin/env python3
"""agentok-bridge — la top issue labellisée agent-ok devient une carte Kanban oa-builder.

Pipeline validé Alex 10 juin : Alex pose le label (ou dit « ok <issue> ») → ce pont
crée la carte → dispatcher (cron 10 min) la spawne → oa-builder produit une PR draft →
oa-athena rejoue les critères → session CC valide le merge → digest montre le RÉSULTAT.
WIP=1 : jamais de nouvelle carte build tant qu'une est active (leçon des 6 drafts morts).
"""
from __future__ import annotations
import argparse
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPOS = ["omar-app", "omar-landing", "omar-hub", "omar-qg", "omar-top", "omar-catalogue"]
PRIO = {"P0": 0, "P1": 1, "P2": 2}


def run(cmd: list[str], timeout: int = 60) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def builder_busy() -> bool:
    txt = run(["/home/omar/.local/bin/hermes", "kanban", "list", "--assignee", "oa-builder"]).stdout
    return any(s in txt for s in ("ready", "running", "claimed", "todo"))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create one oa-builder Kanban card from the highest-priority open GitHub issue labelled agent-ok."
    )
    parser.add_argument("--dry-run", action="store_true", help="Print the selected candidate without creating a Kanban card.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if builder_busy():
        print("WIP=1 : une carte oa-builder est déjà active — pas de nouveau build")
        return
    cands = []
    for repo in REPOS:
        r = run(["/usr/bin/gh", "issue", "list", "-R", f"omar-paris/{repo}", "--label", "agent-ok",
                 "--state", "open", "--json", "number,title,body"])
        if r.returncode != 0:
            print(f"gh KO pour {repo} — ignoré ce passage")
            continue
        cands += [{**it, "repo": repo} for it in json.loads(r.stdout or "[]")]
    if not cands:
        print("aucune issue agent-ok ouverte")
        return
    triage = {}
    try:
        triage = json.loads((ROOT / "var" / "triage.json").read_text())["apps"]
    except Exception:
        pass

    def prio(c: dict) -> int:
        for t in triage.get(c["repo"].replace("omar-", ""), {}).get("top", []):
            if t["number"] == c["number"]:
                return PRIO.get(t["prio"], 2)
        return 2

    cands.sort(key=lambda c: (prio(c), -c["number"]))
    c = cands[0]
    if args.dry_run:
        print(json.dumps({"repo": c["repo"], "number": c["number"], "title": c["title"]}, ensure_ascii=False))
        return
    body = f"""Mission BUILD automatique (pipeline agent-ok — qg#25).

Issue source : https://github.com/omar-paris/{c['repo']}/issues/{c['number']}
Repo local : /home/omar/23-Offre/actifs/{c['repo']}

PROCÉDURE STRICTE :
1. cd dans le repo, git checkout main && git pull, puis branche feat/issue-{c['number']}
2. Implémente UNIQUEMENT le périmètre de l'issue (recopiée ci-dessous)
3. Exécute chaque commande des critères « FAIT » de l'issue — tout doit passer
4. Commit + push + **PR DRAFT** titrée "feat: ... (closes #{c['number']})"
5. complete la carte avec : lien PR + sortie des commandes de critères
INTERDIT : merge, force-push, fichiers hors périmètre, secrets, suppression.

--- ISSUE ---
{c['title']}

{(c['body'] or '')[:4000]}
"""
    res = run(["/home/omar/.local/bin/hermes", "kanban", "create",
               f"build: {c['repo']}#{c['number']} {c['title'][:60]}",
               "--assignee", "oa-builder",
               "--workspace", f"dir:/home/omar/23-Offre/actifs/{c['repo']}",
               "--idempotency-key", f"agentok-{c['repo']}-{c['number']}",
               "--max-runtime", "3600",
               "--body", body])
    print((res.stdout or res.stderr).strip())


if __name__ == "__main__":
    main()
