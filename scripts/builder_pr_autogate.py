#!/usr/bin/env python3
"""Create an oa-athena Kanban review card for each open Builder PR.

Scope: OA repos only. The script is idempotent through the Kanban idempotency key
`builder-pr-gate:<repo>:<number>` and never merges PRs.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

DEFAULT_REPOS = ["omar-app", "omar-qg", "omar-top", "omar-hub", "omar-catalogue"]
REPO_ROOT = Path("/home/omar/23-Offre/actifs")
HERMES = "/home/omar/.local/bin/hermes"
GH = "/usr/bin/gh"


@dataclass(frozen=True)
class PullRequest:
    repo: str
    number: int
    title: str
    url: str
    head_ref: str
    base_ref: str
    is_draft: bool
    author: str | None = None
    body: str | None = None

    @property
    def local_repo(self) -> Path:
        return REPO_ROOT / self.repo


def run(cmd: list[str], *, timeout: int = 60, check: bool = False) -> subprocess.CompletedProcess[str]:
    cp = subprocess.run(cmd, text=True, capture_output=True, timeout=timeout)
    if check and cp.returncode != 0:
        raise RuntimeError(f"command failed ({cp.returncode}): {' '.join(cmd)}\n{cp.stderr.strip()}")
    return cp


def list_open_prs(repo: str) -> list[PullRequest]:
    cp = run([
        GH,
        "pr",
        "list",
        "-R",
        f"omar-paris/{repo}",
        "--state",
        "open",
        "--limit",
        "50",
        "--json",
        "number,title,url,headRefName,baseRefName,isDraft,author,body",
    ], timeout=90, check=True)
    items = json.loads(cp.stdout or "[]")
    return [
        PullRequest(
            repo=repo,
            number=int(item["number"]),
            title=item.get("title") or "",
            url=item.get("url") or "",
            head_ref=item.get("headRefName") or "",
            base_ref=item.get("baseRefName") or "main",
            is_draft=bool(item.get("isDraft")),
            author=(item.get("author") or {}).get("login"),
            body=item.get("body") or "",
        )
        for item in items
    ]


def is_builder_pr(pr: PullRequest) -> bool:
    """Conservative detector: prefer explicit Builder branch/body markers."""
    head = pr.head_ref.lower()
    body = (pr.body or "").lower()
    title = pr.title.lower()
    explicit_body_marker = any(
        marker in body
        for marker in (
            "generated-by: oa-builder",
            "builder-run:",
            "smoke-check builder",
            "micro-diff docs-only pour valider le chemin autonome pr builder",
        )
    )
    return head.startswith("builder/") or (head.startswith("feat/issue-") and explicit_body_marker)


def gate_body(pr: PullRequest) -> str:
    return f"""AUTO-GATE Builder → Athena (sans auto-merge).

PR source : {pr.url}
Repo local : {pr.local_repo}
Base/head : {pr.base_ref} ← {pr.head_ref}
Draft : {pr.is_draft}
Auteur GitHub : {pr.author or 'unknown'}

Mission Athena :
1. Inspecter diff réel de la PR et le contexte main.
2. Exécuter les checks pertinents du repo (tests/build/smoke selon README/package).
3. Vérifier absence de secret et périmètre conforme au body PR/issue.
4. Produire un artefact review_result.json avec verdict `pass`, `pass_with_nits`, `changes_requested`, `reject` ou `decision_required`.
5. Commenter la PR avec le verdict si possible.

Contraintes :
- NE PAS merger.
- NE PAS close.
- Aucun secret dans les logs.
- Si verdict pass/pass_with_nits, laisser H-Omar/default arbitrer merge/release.
"""


def create_gate_card(pr: PullRequest, *, dry_run: bool = False) -> str:
    title = f"gate: {pr.repo}#{pr.number} {pr.title[:70]}"
    key = f"builder-pr-gate:{pr.repo}:{pr.number}"
    cmd = [
        HERMES,
        "kanban",
        "create",
        title,
        "--assignee",
        "oa-athena",
        "--workspace",
        f"dir:{pr.local_repo}",
        "--idempotency-key",
        key,
        "--max-runtime",
        "3600",
        "--body",
        gate_body(pr),
    ]
    if dry_run:
        return f"DRY {key} {pr.url}"
    cp = run(cmd, timeout=90, check=True)
    return (cp.stdout or cp.stderr).strip()


def discover_builder_prs(repos: Iterable[str]) -> list[PullRequest]:
    found: list[PullRequest] = []
    for repo in repos:
        try:
            found.extend(pr for pr in list_open_prs(repo) if is_builder_pr(pr))
        except Exception as exc:
            print(f"WARN {repo}: {exc}", file=sys.stderr)
    return found


def write_status(path: Path, *, status: str, repos: list[str], prs: list[PullRequest], cards: list[str], errors: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "status": status,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "source": "scripts/builder_pr_autogate.py",
        "repos": repos,
        "builder_prs_found": len(prs),
        "builder_prs": [
            {
                "repo": pr.repo,
                "number": pr.number,
                "url": pr.url,
                "head_ref": pr.head_ref,
                "base_ref": pr.base_ref,
                "is_draft": pr.is_draft,
            }
            for pr in prs
        ],
        "cards": cards,
        "last_error": errors[-1] if errors else None,
        "errors": errors,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", action="append", dest="repos", help="Repo name (repeatable). Defaults to OA repos.")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--status-output",
        default="public/api/builder-pr-autogate.json",
        help="Machine-readable Hub/QG status artifact path. Use empty string to disable.",
    )
    args = parser.parse_args(argv)

    repos = args.repos or DEFAULT_REPOS
    errors: list[str] = []
    cards: list[str] = []
    try:
        prs = discover_builder_prs(repos)
        if not prs:
            print("no builder PRs found")
            status = "healthy"
        else:
            status = "healthy"
            for pr in prs:
                try:
                    result = create_gate_card(pr, dry_run=args.dry_run)
                    cards.append(result)
                    print(result)
                except Exception as exc:
                    status = "degraded"
                    errors.append(f"{pr.repo}#{pr.number}: {exc}")
                    print(f"ERROR {pr.repo}#{pr.number}: {exc}", file=sys.stderr)
        if args.status_output:
            write_status(Path(args.status_output), status=status, repos=list(repos), prs=prs, cards=cards, errors=errors)
        return 0 if status == "healthy" else 1
    except Exception as exc:
        errors.append(str(exc))
        if args.status_output:
            write_status(Path(args.status_output), status="down", repos=list(repos), prs=[], cards=cards, errors=errors)
        raise


if __name__ == "__main__":
    raise SystemExit(main())
