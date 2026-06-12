#!/usr/bin/env python3
"""build-ledger.py — collecte les commits du jour (et des 7 derniers jours) sur
chaque repo /home/omar/23-Offre/actifs/omar-* et agrège dans public/api/builds.json.

Sortie : public/api/builds.json
{
  "generated_at": "...Z",
  "today": "2026-06-12",
  "window_days": 7,
  "totals": {"today": N, "window": M, "repos_today": K, "repos_total": R},
  "today_by_repo": [{"repo":..., "name":..., "count":N, "commits":[...]}],
  "days": [{"date": "2026-06-12", "count": N, "repos": [{"repo":..., "name":..., "commits":[...]}]}],
  "deploys": [{"path":..., "mtime":...}]
}

Réutilisé par build.py (import collect_builds) pour que la page /builds/ et les
compteurs home survivent à la reconstruction de public/.

Usage CLI :
    python3 scripts/build-ledger.py            # écrit public/api/builds.json
    python3 scripts/build-ledger.py --print    # affiche le JSON sans écrire
"""
from __future__ import annotations

import argparse
import json
import subprocess
import time
from pathlib import Path

try:
    from zoneinfo import ZoneInfo
except Exception:  # pragma: no cover
    ZoneInfo = None

ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / "public"
ACTIFS = Path("/home/omar/23-Offre/actifs")
WINDOW_DAYS = 7

# Joli nom -> slug de repertoire. Tout omar-* est balayé ; ce mapping ne sert
# qu'à afficher un nom lisible. Les repos non listés gardent leur slug.
REPO_NAMES = {
    "omar-landing": "Landing",
    "omar-app": "AppOmar",
    "omar-catalogue": "Catalogue",
    "omar-qg": "QG",
    "omar-hub": "Hub",
    "omar-top": "OmarTop",
    "omar-top-site": "OmarTop-site",
}


def _paris_today() -> str:
    if ZoneInfo:
        import datetime as dt
        return dt.datetime.now(ZoneInfo("Europe/Paris")).date().isoformat()
    return time.strftime("%Y-%m-%d", time.localtime())


def _git(path: Path, args: list[str]) -> str:
    try:
        return subprocess.check_output(
            ["git", "-C", str(path)] + args, text=True, stderr=subprocess.DEVNULL
        ).strip()
    except Exception:
        return ""


def _repo_dirs() -> list[Path]:
    if not ACTIFS.exists():
        return []
    out = []
    for d in sorted(ACTIFS.glob("omar-*")):
        if (d / ".git").exists():
            out.append(d)
    return out


def _commits(path: Path, since_days: int) -> list[dict]:
    """Commits des `since_days` derniers jours, plus récent d'abord."""
    # Séparateur exotique pour éviter toute collision avec un message de commit.
    fmt = "%h\x1f%an\x1f%ad\x1f%s"
    raw = _git(
        path,
        [
            "log",
            f"--since={since_days} days ago",
            "--date=format-local:%Y-%m-%d %H:%M",
            f"--pretty=format:{fmt}",
        ],
    )
    commits = []
    for line in raw.splitlines():
        parts = line.split("\x1f")
        if len(parts) != 4:
            continue
        h, author, date, subject = parts
        commits.append(
            {
                "hash": h,
                "author": author,
                "date": date,            # "YYYY-MM-DD HH:MM" (heure locale Paris)
                "day": date[:10],
                "message": subject,
            }
        )
    return commits


def _recent_deploys(limit: int = 8) -> list[dict]:
    """Marqueurs de déploiement détectables simplement : fichiers récemment
    modifiés sous public/ (hors api/ regénéré à chaque build)."""
    deploys = []
    if not PUBLIC.exists():
        return deploys
    cutoff = time.time() - WINDOW_DAYS * 86400
    for p in PUBLIC.rglob("index.html"):
        try:
            mt = p.stat().st_mtime
        except OSError:
            continue
        if mt < cutoff:
            continue
        deploys.append(
            {
                "path": str(p.relative_to(PUBLIC)),
                "mtime": time.strftime("%Y-%m-%d %H:%M", time.localtime(mt)),
                "_mt": mt,
            }
        )
    deploys.sort(key=lambda d: d["_mt"], reverse=True)
    for d in deploys:
        d.pop("_mt", None)
    return deploys[:limit]


def collect_builds() -> dict:
    today = _paris_today()
    repos = _repo_dirs()

    today_by_repo = []
    # day -> repo_slug -> {name, commits[]}
    days_map: dict[str, dict[str, dict]] = {}

    window_total = 0
    for path in repos:
        slug = path.name
        name = REPO_NAMES.get(slug, slug)
        commits = _commits(path, WINDOW_DAYS)
        if not commits:
            continue
        window_total += len(commits)

        today_commits = [c for c in commits if c["day"] == today]
        if today_commits:
            today_by_repo.append(
                {"repo": slug, "name": name, "count": len(today_commits), "commits": today_commits}
            )

        for c in commits:
            d = c["day"]
            days_map.setdefault(d, {}).setdefault(slug, {"repo": slug, "name": name, "commits": []})
            days_map[d][slug]["commits"].append(c)

    today_by_repo.sort(key=lambda r: r["count"], reverse=True)

    days = []
    for d in sorted(days_map.keys(), reverse=True):
        repos_for_day = sorted(days_map[d].values(), key=lambda r: len(r["commits"]), reverse=True)
        count = sum(len(r["commits"]) for r in repos_for_day)
        days.append({"date": d, "count": count, "repos": repos_for_day})

    today_count = sum(r["count"] for r in today_by_repo)

    return {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "today": today,
        "window_days": WINDOW_DAYS,
        "totals": {
            "today": today_count,
            "window": window_total,
            "repos_today": len(today_by_repo),
            "repos_total": len(repos),
        },
        "today_by_repo": today_by_repo,
        "days": days,
        "deploys": _recent_deploys(),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--print", action="store_true", dest="just_print", help="Affiche le JSON sans écrire le fichier")
    ap.add_argument("--out", default=str(PUBLIC / "api" / "builds.json"), help="Chemin de sortie")
    args = ap.parse_args()

    data = collect_builds()
    blob = json.dumps(data, ensure_ascii=False, indent=2)
    if args.just_print:
        print(blob)
        return
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(blob, encoding="utf-8")
    t = data["totals"]
    print(f"builds.json → {out} · {t['today']} builds aujourd'hui sur {t['repos_today']} repos · {t['window']} sur {data['window_days']}j")


if __name__ == "__main__":
    main()
