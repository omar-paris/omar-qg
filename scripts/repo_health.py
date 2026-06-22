#!/usr/bin/env python3
"""Collecteur Repo Health OA pour QG.

But: arrêter de redécouvrir l'état Git/GitHub à la main. Le script produit un
snapshot JSON compact, déterministe, consommable par QG et par H-Omar.
Lecture seule: aucune mutation git/github/kanban.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import subprocess
from pathlib import Path
from typing import Any

ACTIFS = Path("/home/omar/23-Offre/actifs")
DEFAULT_REPOS = [
    {"id": "app", "name": "AppOmar", "slug": "omar-app", "repo": "omar-paris/omar-app"},
    {"id": "catalogue", "name": "Catalogue", "slug": "omar-catalogue", "repo": "omar-paris/omar-catalogue"},
    {"id": "hub", "name": "Hub", "slug": "omar-hub", "repo": "omar-paris/omar-hub"},
    {"id": "qg", "name": "QG", "slug": "omar-qg", "repo": "omar-paris/omar-qg"},
    {"id": "omartop", "name": "OmarTop", "slug": "omar-top", "repo": "omar-paris/omar-top"},
]

GENERATED_PREFIXES = (
    "public/api/",
    "public/apps/",
    "public/builds/",
    "public/changelog/",
    "public/clients/",
    "public/decisions/",
    "public/ops/",
    "public/partenaires/",
    "public/objectifs/",
    "public/agent-loop/",
    "var/",
)
GENERATED_NAMES = {"review_result.json"}
NOISY_DIR_PREFIXES = (
    ".athena/",
    ".athena-review-",
    ".builder-worktrees/",
    ".review-worktrees/",
    ".worktrees/",
    "reviews/",
)
SOURCE_PREFIXES = ("scripts/", "tests/", "docs/", "src/", "app/", "components/", "lib/")
SOURCE_NAMES = {"VERSION", "CHANGELOG.md", "README.md", "CONTRACT.md", "package.json", "pyproject.toml"}


def run(cmd: list[str], cwd: Path, timeout: int = 25) -> tuple[int, str, str]:
    try:
        p = subprocess.run(cmd, cwd=cwd, text=True, capture_output=True, timeout=timeout)
        return p.returncode, p.stdout.strip(), p.stderr.strip()
    except Exception as exc:  # pragma: no cover - defensive runtime guard
        return 124, "", f"{exc.__class__.__name__}: {exc}"


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def file_age_hours(repo_path: Path, rel: str) -> float | None:
    p = repo_path / rel
    try:
        if p.is_dir():
            mtimes = [x.stat().st_mtime for x in p.rglob("*") if x.exists()]
            ts = min(mtimes) if mtimes else p.stat().st_mtime
        else:
            ts = p.stat().st_mtime
        age = (dt.datetime.now().timestamp() - ts) / 3600
        return round(max(age, 0), 1)
    except Exception:
        return None


def parse_status(line: str) -> dict[str, Any]:
    code = line[:2]
    path = line[3:] if len(line) > 3 else ""
    if " -> " in path:
        path = path.split(" -> ", 1)[1]
    return {"code": code, "path": path}


def path_class(path: str) -> str:
    if path in GENERATED_NAMES or path.startswith(GENERATED_PREFIXES) or path.startswith(NOISY_DIR_PREFIXES):
        return "generated_or_runtime"
    if path in SOURCE_NAMES or path.startswith(SOURCE_PREFIXES):
        return "source"
    if path.endswith((".py", ".js", ".ts", ".tsx", ".jsx", ".html", ".css", ".md", ".json", ".yaml", ".yml")):
        return "source_candidate"
    return "unknown"


def gh_prs(repo: str) -> list[dict[str, Any]]:
    if not repo:
        return []
    cmd = [
        "gh", "pr", "list", "-R", repo, "--state", "open", "--limit", "20", "--json",
        "number,title,headRefName,baseRefName,isDraft,mergeStateStatus,reviewDecision,updatedAt,url",
    ]
    try:
        p = subprocess.run(cmd, text=True, capture_output=True, timeout=30)
        if p.returncode != 0:
            return []
        data = json.loads(p.stdout or "[]")
        return data if isinstance(data, list) else []
    except Exception:
        return []


def scan_repo(spec: dict[str, str]) -> dict[str, Any]:
    slug = spec["slug"]
    path = ACTIFS / slug
    item: dict[str, Any] = {
        **spec,
        "path": str(path),
        "exists": path.exists(),
        "checked_at": now_iso(),
    }
    if not path.exists():
        item.update({"risk": "P1", "health": "missing", "next_action": "Retrouver le checkout local ou retirer le repo du scope QG."})
        return item

    _, branch, _ = run(["git", "rev-parse", "--abbrev-ref", "HEAD"], path)
    _, head, _ = run(["git", "log", "-1", "--oneline"], path)
    _, upstream, _ = run(["git", "rev-parse", "--abbrev-ref", "@{upstream}"], path)
    ahead = behind = None
    if upstream:
        rc, counts, _ = run(["git", "rev-list", "--left-right", "--count", f"{upstream}...HEAD"], path)
        if rc == 0 and counts:
            parts = counts.split()
            if len(parts) == 2:
                behind, ahead = int(parts[0]), int(parts[1])

    _, status_txt, _ = run(["git", "status", "--short"], path)
    entries = [parse_status(line) for line in status_txt.splitlines() if line.strip()]
    for e in entries:
        e["class"] = path_class(e["path"])
        e["age_hours"] = file_age_hours(path, e["path"])

    dirty_count = len(entries)
    generated_count = sum(1 for e in entries if e["class"] == "generated_or_runtime")
    source_count = sum(1 for e in entries if e["class"] in {"source", "source_candidate"})
    oldest_dirty_age = max((e["age_hours"] for e in entries if e["age_hours"] is not None), default=None)
    prs = gh_prs(spec.get("repo", ""))
    branch_prs = [p for p in prs if p.get("headRefName") == branch]
    conflict_prs = [p for p in prs if p.get("mergeStateStatus") == "DIRTY"]

    risk = "OK"
    health = "clean"
    if dirty_count:
        health = "dirty"
        risk = "P2"
    if source_count or (oldest_dirty_age is not None and oldest_dirty_age >= 24) or (ahead or 0) > 0:
        risk = "P1"
    if conflict_prs or (dirty_count >= 25 and oldest_dirty_age is not None and oldest_dirty_age >= 72):
        risk = "P0"

    if not dirty_count and not prs:
        next_action = "Aucune action repo-health."
    elif conflict_prs:
        nums = ", ".join(f"#{p['number']}" for p in conflict_prs)
        next_action = f"Résoudre conflit PR {nums}, puis relancer gate Athena."
    elif dirty_count and generated_count == dirty_count:
        next_action = "Classer generated/runtime: nettoyer si timestamp/cache, sinon intégrer au pipeline QG."
    elif dirty_count:
        next_action = "Inspecter diff, séparer source utile vs généré, puis commit/PR ou clean documenté."
    elif prs:
        next_action = "Vérifier gate Athena / merge decision pour PR ouverte."
    else:
        next_action = "Surveillance normale."

    item.update({
        "branch": branch,
        "upstream": upstream,
        "head": head,
        "ahead": ahead,
        "behind": behind,
        "dirty_count": dirty_count,
        "generated_or_runtime_count": generated_count,
        "source_candidate_count": source_count,
        "oldest_dirty_age_hours": oldest_dirty_age,
        "dirty_entries": entries[:80],
        "open_prs": prs,
        "branch_prs": branch_prs,
        "conflict_prs": conflict_prs,
        "risk": risk,
        "health": health,
        "next_action": next_action,
    })
    return item


def collect() -> dict[str, Any]:
    repos = [scan_repo(r) for r in DEFAULT_REPOS]
    risk_order = {"P0": 0, "P1": 1, "P2": 2, "OK": 3}
    repos.sort(key=lambda r: (risk_order.get(str(r.get("risk")), 9), -int(r.get("dirty_count") or 0), r.get("slug", "")))
    totals = {
        "repos": len(repos),
        "dirty": sum(1 for r in repos if r.get("dirty_count")),
        "p0": sum(1 for r in repos if r.get("risk") == "P0"),
        "p1": sum(1 for r in repos if r.get("risk") == "P1"),
        "p2": sum(1 for r in repos if r.get("risk") == "P2"),
        "ok": sum(1 for r in repos if r.get("risk") == "OK"),
        "open_prs": sum(len(r.get("open_prs") or []) for r in repos),
        "conflict_prs": sum(len(r.get("conflict_prs") or []) for r in repos),
        "source_candidates": sum(int(r.get("source_candidate_count") or 0) for r in repos),
        "generated_or_runtime": sum(int(r.get("generated_or_runtime_count") or 0) for r in repos),
    }
    alerts = []
    if totals["p0"]:
        alerts.append({"level": "P0", "code": "REPO_HEALTH_P0", "message": f"{totals['p0']} repo(s) avec conflit PR ou drift long massif."})
    if totals["dirty"]:
        alerts.append({"level": "P1", "code": "DIRTY_REPOS", "message": f"{totals['dirty']} repo(s) locaux dirty — action propriétaire obligatoire."})
    return {
        "schema": "oa.repo-health/1",
        "generated_at": now_iso(),
        "source": "scripts/repo_health.py",
        "thresholds": {
            "dirty_files_p1": ">0 source candidate OR oldest dirty >=24h OR local commits ahead",
            "dirty_files_p0": ">=25 dirty files AND oldest dirty >=72h",
            "pr_conflict_p0": "any open PR mergeStateStatus=DIRTY",
        },
        "totals": totals,
        "alerts": alerts,
        "repos": repos,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="public/api/repo-health.json")
    parser.add_argument("--var-output", default="var/repo-health.json")
    args = parser.parse_args()
    payload = collect()
    for raw in [args.output, args.var_output]:
        if not raw:
            continue
        out = Path(raw)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"generated_at": payload["generated_at"], "totals": payload["totals"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
