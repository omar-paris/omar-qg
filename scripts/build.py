#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import ssl
import subprocess
import time
import urllib.error
import urllib.request
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / "public"
ACTIFS = Path("/home/omar/23-Offre/actifs")
VERSION = "V" + (ROOT / "VERSION").read_text(encoding="utf-8").strip()
DOMAIN = "qg.omar.paris"

# ── GitHub token ──────────────────────────────────────────────────────────────

def _gh_token() -> str:
    t = os.environ.get("GITHUB_TOKEN", "")
    if t:
        return t
    try:
        return subprocess.check_output(
            ["gh", "auth", "token"], text=True, stderr=subprocess.DEVNULL
        ).strip()
    except Exception:
        return ""

GH_TOKEN = _gh_token()

_SSL = ssl.create_default_context()
_SSL.check_hostname = False
_SSL.verify_mode = ssl.CERT_NONE

# ── Registry items ────────────────────────────────────────────────────────────

ITEMS = [
    {"id": "landing",  "name": "Landing",   "domain": "landing.omar.paris",   "repo": "omar-paris/omar-landing",   "path": "omar-landing",   "scope": "CORE OA",       "role": "Vitrine publique. CTA → AppOmar.",                                  "version": "V0.2.0", "changelog": "https://landing.omar.paris/changelog/",   "next": "Harmoniser CTA vers app.omar.paris."},
    {"id": "app",      "name": "AppOmar",   "domain": "app.omar.paris",       "repo": "omar-paris/omar-app",       "path": "omar-app",       "scope": "CORE OA",       "role": "Portail client : onboarding, config, buy, SAV, factures.",          "version": "V0.3.0", "changelog": "https://app.omar.paris/changelog/",       "next": "Persister Caddy public/DNS, rendre config interactif."},
    {"id": "catalogue","name": "Catalogue", "domain": "catalogue.omar.paris", "repo": "omar-paris/omar-catalogue", "path": "omar-catalogue", "scope": "CORE OA",       "role": "Recommandations Apps, Agents, Tools, Skills, MCP, Bundles.",        "version": "V0.7.3", "changelog": "https://catalogue.omar.paris/changelog/", "next": "Enrichir recommandations."},
    {"id": "lab",      "name": "Lab",       "domain": "lab.omar.paris",       "repo": "",                          "path": "oa-lab-plane",   "scope": "CORE OA",       "role": "Atelier Plane : projets, work items, cycles.",                      "version": "Plane",  "changelog": "https://lab.omar.paris/",                 "next": "Consolider projets → CORE/VPS/DIVERS/ARCHIVE."},
    {"id": "qg",       "name": "QG",        "domain": "qg.omar.paris",        "repo": "omar-paris/omar-qg",        "path": "omar-qg",        "scope": "CORE OA",       "role": "Registry opérationnel : versions, health, issues, PRs.",            "version": "V0.3.0", "changelog": "https://qg.omar.paris/changelog/",        "next": "Rebuild cron actif 30 min."},
    {"id": "hub",      "name": "Hub",       "domain": "hub.omar.paris",       "repo": "omar-paris/omar-hub",       "path": "omar-hub",       "scope": "VPS Hermes OA", "role": "Cockpit local VPS.",                                                "version": "V0.9.2", "changelog": "https://hub.omar.paris/changelog/",       "next": "Harmoniser VERSION."},
    {"id": "omartop",  "name": "OmarTop",   "domain": "top.omar.paris",       "repo": "omar-paris/omar-top",       "path": "omar-top",       "scope": "VPS Hermes OA", "role": "Référence stack VPS Hermes OA : standards, maturité, contrôles.",   "version": "0.3.0-rc1", "changelog": "https://top.omar.paris/changelog/",    "next": "Stabiliser rc1."},
]

# ── Partners catalog ──────────────────────────────────────────────────────────

PARTNERS = [
    {
        "id": "hetzner",
        "name": "Hetzner",
        "url": "https://www.hetzner.com",
        "logo": "H",
        "color": "#d50c2d",
        "role": "VPS et serveurs dédiés clients",
        "vault_key": "secret/integrations/hetzner",
        "api_status": "key_pending",
        "offers": [
            {"ref": "CAX11", "name": "CAX11 ARM",     "vcpu": 2,  "ram_gb": 4,  "disk_gb": 40,  "price_eur": 3.79,  "type": "VPS ARM",    "note": "Entrée de gamme ARM — client solo"},
            {"ref": "CAX21", "name": "CAX21 ARM",     "vcpu": 4,  "ram_gb": 8,  "disk_gb": 80,  "price_eur": 7.49,  "type": "VPS ARM",    "note": "Pack standard client"},
            {"ref": "CAX31", "name": "CAX31 ARM",     "vcpu": 8,  "ram_gb": 16, "disk_gb": 160, "price_eur": 14.99, "type": "VPS ARM",    "note": "Pack Pro client"},
            {"ref": "CPX11", "name": "CPX11 Intel",   "vcpu": 2,  "ram_gb": 2,  "disk_gb": 40,  "price_eur": 4.15,  "type": "VPS Intel",  "note": "Alternative x86"},
            {"ref": "CPX21", "name": "CPX21 Intel",   "vcpu": 3,  "ram_gb": 4,  "disk_gb": 80,  "price_eur": 6.39,  "type": "VPS Intel",  "note": "Alternative x86 standard"},
            {"ref": "backup", "name": "Backup 50 GB", "vcpu": None, "ram_gb": None, "disk_gb": 50, "price_eur": 1.19, "type": "Backup",   "note": "Backup volume S3-compatible"},
        ],
    },
    {
        "id": "ovh",
        "name": "OVH",
        "url": "https://www.ovh.com/fr/",
        "logo": "O",
        "color": "#0050d7",
        "role": "Domaines, DNS, email, VPS complémentaires",
        "vault_key": "secret/integrations/ovh",
        "api_status": "key_ok_rights_pending",
        "offers": [
            {"ref": "vps-starter", "name": "VPS Starter",   "vcpu": 1, "ram_gb": 2,  "disk_gb": 20,  "price_eur": 3.50,  "type": "VPS",     "note": "Entrée de gamme"},
            {"ref": "vps-value",   "name": "VPS Value",     "vcpu": 1, "ram_gb": 2,  "disk_gb": 40,  "price_eur": 6.00,  "type": "VPS",     "note": "Standard"},
            {"ref": "domain-fr",   "name": "Domaine .fr",   "vcpu": None, "ram_gb": None, "disk_gb": None, "price_eur": 6.99, "type": "Domaine", "note": "Annuel"},
            {"ref": "domain-com",  "name": "Domaine .com",  "vcpu": None, "ram_gb": None, "disk_gb": None, "price_eur": 9.99, "type": "Domaine", "note": "Annuel"},
            {"ref": "mx-starter",  "name": "MX Plan Starter","vcpu": None,"ram_gb": None, "disk_gb": 1,   "price_eur": 0.0,   "type": "Email",   "note": "Gratuit / inclus domaine"},
        ],
    },
    {
        "id": "infomaniak",
        "name": "Infomaniak",
        "url": "https://www.infomaniak.com/fr",
        "logo": "I",
        "color": "#00b04f",
        "role": "Email pro, DNS suisse, kDrive, backup",
        "vault_key": "secret/integrations/infomaniak",
        "api_status": "key_pending",
        "offers": [
            {"ref": "mail-1",    "name": "Mail 1 boîte",   "vcpu": None, "ram_gb": None, "disk_gb": 25,  "price_eur": 1.25,  "type": "Email",   "note": "Par boîte/mois"},
            {"ref": "mail-5",    "name": "Mail 5 boîtes",  "vcpu": None, "ram_gb": None, "disk_gb": 25,  "price_eur": 4.99,  "type": "Email",   "note": "Pack 5 boîtes"},
            {"ref": "kdrive-15", "name": "kDrive 15 Go",   "vcpu": None, "ram_gb": None, "disk_gb": 15,  "price_eur": 3.99,  "type": "Stockage","note": "Cloud suisse"},
            {"ref": "swiss-bkp", "name": "Swiss Backup S", "vcpu": None, "ram_gb": None, "disk_gb": 200, "price_eur": 4.99,  "type": "Backup",  "note": "Sauvegarde chiffrée CH"},
            {"ref": "domain-ch", "name": "Domaine .ch",    "vcpu": None, "ram_gb": None, "disk_gb": None,"price_eur": 9.50,  "type": "Domaine", "note": "Annuel"},
        ],
    },
]

# ── Data fetchers ─────────────────────────────────────────────────────────────

def _gh_get(url: str) -> object:
    if not GH_TOKEN:
        return None
    req = urllib.request.Request(
        url,
        headers={"Authorization": f"Bearer {GH_TOKEN}", "Accept": "application/vnd.github+json", "User-Agent": "OA-QG/1.0"},
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return json.loads(r.read().decode())
    except Exception:
        return None


def github_state(repo_slug: str) -> dict:
    base = {"open_issues": None, "open_prs": None, "last_merged_pr": None}
    if not repo_slug or "/" not in repo_slug or not GH_TOKEN:
        return base
    repo_data = _gh_get(f"https://api.github.com/repos/{repo_slug}")
    if not isinstance(repo_data, dict):
        return base
    prs_open = _gh_get(f"https://api.github.com/repos/{repo_slug}/pulls?state=open&per_page=10")
    open_prs = len(prs_open) if isinstance(prs_open, list) else None
    total_with_prs = repo_data.get("open_issues_count", 0)
    open_issues = max(0, total_with_prs - (open_prs or 0)) if open_prs is not None else total_with_prs
    prs_closed = _gh_get(f"https://api.github.com/repos/{repo_slug}/pulls?state=closed&per_page=1&sort=updated&direction=desc")
    last_merged = None
    if isinstance(prs_closed, list) and prs_closed and prs_closed[0].get("merged_at"):
        pr = prs_closed[0]
        last_merged = {"title": pr["title"], "number": pr["number"], "merged_at": pr["merged_at"]}
    return {"open_issues": open_issues, "open_prs": open_prs, "last_merged_pr": last_merged}


def health_probe(domain: str) -> dict:
    url = f"https://{domain}/"
    t0 = time.monotonic()
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "OA-QG-probe/1.0"})
        with urllib.request.urlopen(req, timeout=8, context=_SSL) as r:
            latency_ms = int((time.monotonic() - t0) * 1000)
            return {"status": "ok", "http_code": r.status, "latency_ms": latency_ms}
    except urllib.error.HTTPError as e:
        latency_ms = int((time.monotonic() - t0) * 1000)
        return {"status": "ok" if e.code < 500 else "error", "http_code": e.code, "latency_ms": latency_ms}
    except Exception:
        return {"status": "error", "http_code": None, "latency_ms": None}


def git_state(path_slug: str) -> dict:
    path = ACTIFS / path_slug
    if not path.exists():
        return {"exists": False, "branch": "missing", "dirty": False, "head": ""}
    def run(args):
        try:
            return subprocess.check_output(args, cwd=path, text=True, stderr=subprocess.DEVNULL).strip()
        except Exception:
            return ""
    def clean(v):
        return (v or "").replace("admin-app", "AppOmar")
    branch = run(["git", "rev-parse", "--abbrev-ref", "HEAD"])
    if path_slug == "omar-qg":
        head = "current qg build"
        status = run(["git", "status", "--short", "--", ".", ":!public"])
    else:
        head = clean(run(["git", "log", "-1", "--oneline"]))
        status = clean(run(["git", "status", "--short"]))
    return {"exists": True, "branch": branch or "no-git", "dirty": bool(status), "head": head, "status_short": status.splitlines()[:8]}


def payload(built_at: str) -> dict:
    items = []
    for item in ITEMS:
        enriched = dict(item)
        enriched["git"] = git_state(item["path"])
        enriched["github"] = github_state(item.get("repo", ""))
        enriched["health"] = health_probe(item["domain"])
        items.append(enriched)
    healthy = sum(1 for i in items if i["health"]["status"] == "ok")
    counts = {
        "total": len(items),
        "core": sum(1 for i in items if i["scope"] == "CORE OA"),
        "vps": sum(1 for i in items if i["scope"] == "VPS Hermes OA"),
        "healthy": healthy,
        "open_issues_total": sum(i["github"]["open_issues"] or 0 for i in items),
        "open_prs_total": sum(i["github"]["open_prs"] or 0 for i in items),
    }
    return {"version": VERSION, "domain": DOMAIN, "built_at": built_at, "items": items, "counts": counts, "partners": PARTNERS}


# ── HTML layout ───────────────────────────────────────────────────────────────

TAILWIND = "https://cdn.tailwindcss.com"
FONTS    = "https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap"

NAV_ITEMS = [
    ("/",             "registry", "Registry",    '<path stroke-linecap="round" stroke-linejoin="round" d="M3.75 12h16.5m-16.5 3.75h16.5M3.75 19.5h16.5M5.625 4.5h12.75a1.875 1.875 0 0 1 0 3.75H5.625a1.875 1.875 0 0 1 0-3.75Z"/>'),
    ("/partenaires/", "partenaires", "Partenaires", '<path stroke-linecap="round" stroke-linejoin="round" d="M13.5 21v-7.5a.75.75 0 0 1 .75-.75h3a.75.75 0 0 1 .75.75V21m-4.5 0H2.36m11.14 0H18m0 0h3.64m-1.39 0V9.349M3.75 21V9.349m0 0a3.001 3.001 0 0 0 3.75-.615A2.993 2.993 0 0 0 9.75 9.75c.896 0 1.7-.393 2.25-1.016a2.993 2.993 0 0 0 2.25 1.016 2.993 2.993 0 0 0 2.25-1.015M3.75 9.349a3 3 0 0 0 3.75.616m-3.75-.616a3.001 3.001 0 0 1-.75-1.99V6h17.25v1.36a3 3 0 0 1-.75 1.99m0 0a2.993 2.993 0 0 1-2.25 1.016"/>'),
    ("/changelog/",   "changelog",  "Changelog",   '<path stroke-linecap="round" stroke-linejoin="round" d="M12 6v6h4.5m4.5 0a9 9 0 1 1-18 0 9 9 0 0 1 18 0Z"/>'),
]


def _icon(path_d: str, cls: str = "w-5 h-5") -> str:
    return f'<svg class="{cls}" fill="none" viewBox="0 0 24 24" stroke-width="1.7" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="{escape(path_d)}"/></svg>'


def sidebar(active: str, built_at: str) -> str:
    nav_links = ""
    for href, key, label, icon_d in NAV_ITEMS:
        is_active = active == key
        active_cls = "bg-blue-50 text-blue-700" if is_active else "text-gray-600 hover:bg-gray-50 hover:text-gray-900"
        icon_cls = "w-5 h-5 " + ("text-blue-600" if is_active else "text-gray-400")
        nav_links += (
            f'<a href="{href}" class="flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium {active_cls} transition-colors">'
            f'<svg class="{icon_cls}" fill="none" viewBox="0 0 24 24" stroke-width="1.7" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="{escape(icon_d)}"/></svg>'
            f'{escape(label)}</a>'
        )
    ts_short = built_at[11:16] + "Z" if len(built_at) > 16 else built_at
    return f"""
<aside class="fixed inset-y-0 left-0 w-64 bg-white border-r border-gray-200 flex flex-col z-30 hidden md:flex">
  <div class="px-5 py-4 border-b border-gray-100">
    <div class="flex items-center gap-3">
      <div class="w-9 h-9 rounded-lg bg-blue-600 text-white text-sm font-bold flex items-center justify-center">QG</div>
      <div>
        <div class="text-sm font-bold text-gray-900">OA QG</div>
        <div class="text-xs text-gray-400">{VERSION} · {escape(DOMAIN)}</div>
      </div>
    </div>
  </div>
  <nav class="flex-1 px-3 py-3 space-y-0.5 overflow-y-auto">{nav_links}</nav>
  <div class="px-5 py-3 border-t border-gray-100">
    <div class="text-xs text-gray-400">Mis à jour {escape(ts_short)}</div>
    <a href="/api/core-repos.json" class="text-xs text-blue-500 hover:underline">API JSON</a>
  </div>
</aside>
<div class="md:hidden bg-white border-b border-gray-200 px-4 py-3 flex items-center gap-3 sticky top-0 z-20">
  <div class="w-8 h-8 rounded bg-blue-600 text-white text-xs font-bold flex items-center justify-center">QG</div>
  <nav class="flex gap-1">{''.join(f'<a href="{h}" class="px-3 py-1.5 rounded text-xs font-medium {"bg-blue-50 text-blue-700" if a==active else "text-gray-600"}">{escape(l)}</a>' for h,a,l,_ in NAV_ITEMS)}</nav>
</div>"""


def layout(active: str, title: str, built_at: str, body: str) -> str:
    return f"""<!doctype html><html lang="fr"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{escape(title)} · OA QG</title>
<meta name="qg-version" content="{VERSION}">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="{FONTS}" rel="stylesheet">
<script src="{TAILWIND}"></script>
<script>tailwind.config={{theme:{{extend:{{fontFamily:{{sans:['Inter','system-ui','sans-serif']}}}}}}}}</script>
<style>body{{font-family:'Inter',system-ui,sans-serif}}.pill-ok{{background:#f0fdf4;color:#166534;border:1px solid #bbf7d0}}.pill-warn{{background:#fffbeb;color:#92400e;border:1px solid #fde68a}}.pill-err{{background:#fef2f2;color:#991b1b;border:1px solid #fecaca}}</style>
</head>
<body class="bg-gray-50 text-slate-800 min-h-screen">
{sidebar(active, built_at)}
<main class="md:ml-64 min-h-screen">
<div class="px-6 py-6 max-w-6xl">{body}</div>
</main>
</body></html>"""


# ── Pages ─────────────────────────────────────────────────────────────────────

def page_registry(data: dict) -> str:
    items = data["items"]
    counts = data["counts"]

    # Stats bar
    stats = (
        f'<div class="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-6">'
        f'<div class="bg-white rounded-xl border border-gray-200 px-4 py-3"><div class="text-2xl font-bold text-gray-900">{counts["healthy"]}<span class="text-gray-400 text-sm font-normal">/{counts["total"]}</span></div><div class="text-xs text-gray-500 mt-0.5">Healthy</div></div>'
        f'<div class="bg-white rounded-xl border border-gray-200 px-4 py-3"><div class="text-2xl font-bold text-gray-900">{counts["open_issues_total"]}</div><div class="text-xs text-gray-500 mt-0.5">Issues ouvertes</div></div>'
        f'<div class="bg-white rounded-xl border border-gray-200 px-4 py-3"><div class="text-2xl font-bold text-gray-900">{counts["open_prs_total"]}</div><div class="text-xs text-gray-500 mt-0.5">PRs ouvertes</div></div>'
        f'<div class="bg-white rounded-xl border border-gray-200 px-4 py-3"><div class="text-2xl font-bold text-gray-900">{counts["core"]}</div><div class="text-xs text-gray-500 mt-0.5">Apps CORE OA</div></div>'
        f'</div>'
    )

    # Table header
    rows = (
        '<div class="bg-white rounded-xl border border-gray-200 overflow-hidden">'
        '<div class="grid grid-cols-[1fr_100px_110px_100px_100px] gap-2 px-4 py-2.5 bg-gray-50 border-b border-gray-200 text-xs font-semibold text-gray-500 uppercase tracking-wide hidden md:grid">'
        '<span>App</span><span>Health</span><span>Issues / PRs</span><span>Version</span><span>Git</span>'
        '</div>'
    )
    for item in items:
        h = item["health"]
        gh = item["github"]
        git = item["git"]
        repo = item.get("repo", "")

        # Health pill
        if h["status"] == "ok":
            lat = f' · {h["latency_ms"]}ms' if h.get("latency_ms") else ""
            h_pill = f'<span class="pill-ok inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium">{h.get("http_code","ok")}{escape(lat)}</span>'
        elif h.get("http_code"):
            h_pill = f'<span class="pill-warn inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium">{h["http_code"]}</span>'
        else:
            h_pill = '<span class="pill-err inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium">down</span>'

        # GitHub
        iss = gh.get("open_issues")
        prs = gh.get("open_prs")
        if iss is not None and repo:
            gh_html = f'<a href="https://github.com/{escape(repo)}/issues" class="text-xs text-gray-500 hover:text-blue-600">{iss} issues</a>'
        elif iss is not None:
            gh_html = f'<span class="text-xs text-gray-500">{iss} issues</span>'
        else:
            gh_html = '<span class="text-xs text-gray-300">—</span>'
        if prs is not None and repo:
            gh_html += f' <a href="https://github.com/{escape(repo)}/pulls" class="text-xs text-gray-500 hover:text-blue-600">{prs} PRs</a>'

        # Git dirty
        dirty = git.get("dirty", False)
        git_pill = f'<span class="{"pill-warn" if dirty else "pill-ok"} inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium">{"dirty" if dirty else "clean"}</span>'

        # Scope badge
        scope_cls = "bg-blue-50 text-blue-700" if item["scope"] == "CORE OA" else "bg-violet-50 text-violet-700"

        rows += (
            f'<div class="grid md:grid-cols-[1fr_100px_110px_100px_100px] gap-2 px-4 py-3.5 border-b border-gray-100 last:border-0 items-start hover:bg-gray-50">'
            f'<div><div class="flex items-center gap-2 mb-0.5">'
            f'<span class="text-sm font-semibold text-gray-900">{escape(item["name"])}</span>'
            f'<span class="text-xs rounded px-1.5 py-0.5 {scope_cls}">{escape(item["scope"])}</span>'
            f'</div>'
            f'<div class="text-xs text-gray-500 mb-1.5">{escape(item["role"])}</div>'
            f'<div class="flex gap-2 flex-wrap">'
            f'<a href="https://{escape(item["domain"])}/" class="text-xs text-blue-500 hover:underline">{escape(item["domain"])}</a>'
            + (f' <a href="https://github.com/{escape(repo)}" class="text-xs text-gray-400 hover:text-gray-600">GitHub</a>' if repo else '')
            + f'</div></div>'
            f'<div class="flex items-center">{h_pill}</div>'
            f'<div class="flex flex-col gap-0.5">{gh_html}</div>'
            f'<div class="flex items-center"><span class="text-xs font-mono bg-gray-100 rounded px-1.5 py-0.5 text-gray-700">{escape(item["version"])}</span></div>'
            f'<div class="flex items-center">{git_pill}</div>'
            f'</div>'
        )
    rows += '</div>'

    header = '<div class="flex items-center justify-between mb-6"><h1 class="text-xl font-bold text-gray-900">Registry CORE OA</h1><span class="text-xs text-gray-400">Rebuild auto · 30 min</span></div>'
    return header + stats + rows


def _api_badge(status: str) -> str:
    labels = {
        "ok":                    ("bg-green-50 text-green-700 border border-green-200",  "API OK"),
        "key_ok_rights_pending": ("bg-yellow-50 text-yellow-700 border border-yellow-200","Clef OK · droits en attente"),
        "key_pending":           ("bg-gray-100 text-gray-600 border border-gray-200",     "Clef à configurer"),
        "error":                 ("bg-red-50 text-red-700 border border-red-200",         "Erreur"),
    }
    cls, label = labels.get(status, ("bg-gray-100 text-gray-500","?"))
    return f'<span class="inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium {cls}">{escape(label)}</span>'


def page_partenaires(data: dict) -> str:
    partners = data["partners"]
    html = '<div class="mb-6"><h1 class="text-xl font-bold text-gray-900">Partenaires & fournisseurs</h1><p class="text-sm text-gray-500 mt-1">Offres disponibles pour provisionner les stacks clients. Les VPS clients seront listés ici une fois les API connectées.</p></div>'

    for p in partners:
        offers_html = ""
        for o in p["offers"]:
            specs = []
            if o.get("vcpu"):    specs.append(f'{o["vcpu"]} vCPU')
            if o.get("ram_gb"):  specs.append(f'{o["ram_gb"]} Go RAM')
            if o.get("disk_gb"): specs.append(f'{o["disk_gb"]} Go')
            specs_str = " · ".join(specs) if specs else "—"
            type_cls = {
                "VPS ARM": "bg-purple-50 text-purple-700", "VPS Intel": "bg-blue-50 text-blue-700",
                "VPS": "bg-blue-50 text-blue-700", "Backup": "bg-orange-50 text-orange-700",
                "Stockage": "bg-orange-50 text-orange-700", "Email": "bg-green-50 text-green-700",
                "Domaine": "bg-gray-100 text-gray-700",
            }.get(o["type"], "bg-gray-100 text-gray-600")
            price_str = "gratuit" if o["price_eur"] == 0.0 else f'{o["price_eur"]:.2f} €/mois'
            offers_html += (
                f'<div class="flex items-center justify-between py-2.5 border-b border-gray-100 last:border-0">'
                f'<div>'
                f'<div class="flex items-center gap-2"><span class="text-sm font-medium text-gray-900">{escape(o["name"])}</span>'
                f'<span class="text-xs rounded px-1.5 py-0.5 {type_cls}">{escape(o["type"])}</span></div>'
                f'<div class="text-xs text-gray-400 mt-0.5">{escape(specs_str)}{(" · " + escape(o["note"])) if o.get("note") else ""}</div>'
                f'</div>'
                f'<div class="text-sm font-semibold text-gray-900 ml-4 shrink-0">{escape(price_str)}</div>'
                f'</div>'
            )

        color = p["color"]
        html += (
            f'<div class="bg-white rounded-xl border border-gray-200 mb-5">'
            f'<div class="flex items-center justify-between px-5 py-4 border-b border-gray-100">'
            f'<div class="flex items-center gap-3">'
            f'<div class="w-9 h-9 rounded-lg text-white text-sm font-bold flex items-center justify-center" style="background:{escape(color)}">{escape(p["logo"])}</div>'
            f'<div><div class="text-sm font-bold text-gray-900">{escape(p["name"])}</div>'
            f'<div class="text-xs text-gray-500">{escape(p["role"])}</div></div>'
            f'</div>'
            f'<div class="flex items-center gap-2">'
            f'{_api_badge(p["api_status"])}'
            f'<a href="{escape(p["url"])}" class="text-xs text-blue-500 hover:underline" target="_blank">Site</a>'
            f'<span class="text-xs text-gray-300 font-mono">{escape(p["vault_key"])}</span>'
            f'</div></div>'
            f'<div class="px-5 py-1">{offers_html}</div>'
            f'</div>'
        )

    # VPS clients placeholder
    html += (
        '<div class="bg-blue-50 border border-blue-200 rounded-xl px-5 py-4 mt-2">'
        '<div class="text-sm font-semibold text-blue-800 mb-1">VPS clients — à venir</div>'
        '<div class="text-xs text-blue-600">Une fois les API Hetzner et OVH connectées, cette section listera les VPS provisionnés par client avec leur configuration, coût mensuel et état.</div>'
        '</div>'
    )
    return html


def page_changelog() -> str:
    cl = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    lines = cl.splitlines()
    html = '<h1 class="text-xl font-bold text-gray-900 mb-6">Changelog</h1>'
    html += '<div class="bg-white rounded-xl border border-gray-200 px-6 py-5 prose prose-sm max-w-none">'
    for line in lines:
        if line.startswith("## "):
            html += f'<h2 class="text-base font-bold text-gray-800 mt-5 mb-2 first:mt-0">{escape(line[3:])}</h2>'
        elif line.startswith("# "):
            pass
        elif line.startswith("- "):
            html += f'<div class="flex gap-2 text-sm text-gray-600 py-0.5"><span class="text-gray-300 shrink-0">—</span><span>{escape(line[2:])}</span></div>'
        elif line.strip():
            html += f'<p class="text-sm text-gray-600 mt-1">{escape(line)}</p>'
    html += "</div>"
    return html


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    built_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    data = payload(built_at)

    tmp = PUBLIC.parent / "public_build_tmp"
    if tmp.exists():
        import shutil
        shutil.rmtree(tmp)
    (tmp / "api").mkdir(parents=True)

    (tmp / "api" / "core-repos.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    pages = [
        ("/",             "registry",    "Registry CORE OA",        page_registry(data)),
        ("/partenaires/", "partenaires", "Partenaires",              page_partenaires(data)),
        ("/changelog/",   "changelog",   "Changelog",                page_changelog()),
    ]
    for route, active, title, body in pages:
        out = tmp / "index.html" if route == "/" else tmp / route.strip("/") / "index.html"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(layout(active, title, built_at, body), encoding="utf-8")

    if PUBLIC.exists():
        import shutil
        shutil.rmtree(PUBLIC)
    tmp.rename(PUBLIC)

    healthy = data["counts"]["healthy"]
    issues  = data["counts"]["open_issues_total"]
    prs     = data["counts"]["open_prs_total"]
    print(f"built qg {len(pages)} routes · {healthy}/{data['counts']['total']} healthy · {issues} issues · {prs} PRs · {built_at}")


if __name__ == "__main__":
    main()
