#!/usr/bin/env python3
from __future__ import annotations

import datetime as dt
import json
import os
import ssl
import sqlite3
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / "public"
ACTIFS = Path("/home/omar/23-Offre/actifs")


def _load_build_ledger():
    """Importe scripts/build-ledger.py (nom à tiret → importlib)."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "build_ledger", Path(__file__).resolve().parent / "build-ledger.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

VERSION = "V" + (ROOT / "VERSION").read_text(encoding="utf-8").strip()
DOMAIN = "qg.omar.paris"
STATE_DB = Path("/home/omar/.hermes/state.db")
BUILD_LEDGER_DIR = Path("/home/omar/11-Pilotage/ledgers/builds")
try:
    from zoneinfo import ZoneInfo
except Exception:  # pragma: no cover
    ZoneInfo = None

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
    {"id": "hub",      "name": "Hub",       "domain": "hub.omar.paris",       "repo": "omar-paris/omar-hub",       "path": "omar-hub",       "scope": "CORE OA",       "role": "App N°1 : relie chaque VPS à OA. Répliquée sur tout VPS (L0/L1). Vue = version installée ici.",                                                "version": "V0.9.2", "changelog": "https://hub.omar.paris/changelog/",       "next": "Harmoniser VERSION."},
    {"id": "omartop",  "name": "OmarTop",   "domain": "top.omar.paris",       "repo": "omar-paris/omar-top",       "path": "omar-top",       "scope": "CORE OA",       "role": "Référence/doctrine : standards, maturité, contrôles (L0→L3 par VPS).",   "version": "0.3.0-rc1", "changelog": "https://top.omar.paris/changelog/",    "next": "Stabiliser rc1."},
]

# ── Providers ─────────────────────────────────────────────────────────────────

PROVIDERS = {
    "hetzner":     {"name": "Hetzner",     "logo": "H", "color": "#d50c2d", "url": "https://www.hetzner.com",       "vault_key": "secret/integrations/hetzner/prod"},
    "ovh":         {"name": "OVH",         "logo": "O", "color": "#0050d7", "url": "https://www.ovh.com/fr/",       "vault_key": "secret/integrations/ovh"},
    "infomaniak":  {"name": "Infomaniak",  "logo": "I", "color": "#00b04f", "url": "https://www.infomaniak.com/fr", "vault_key": "secret/integrations/infomaniak"},
    "telnyx":      {"name": "Telnyx",      "logo": "T", "color": "#00c89c", "url": "https://telnyx.com",            "vault_key": "secret/integrations/telnyx"},
}

# ── VPS metadata ──────────────────────────────────────────────────────────────
# Keyed by substring matched against the Hetzner server name.
# Live data (specs, IP, status, cost…) comes from the Hetzner API at build.
# Static metadata (role, owner, monitoring + local page links) defined here.

VPS_META = {
    "omar": {
        "label": "VPS-Omar",
        "role": "CORE OA",
        "role_color": "#0050d7",
        "owner": "OA / Alex",
        "purpose": "Infra centrale : agents Hermes, Caddy, Vault, sites CORE OA, QG.",
        "tailnet": "100.79.68.6",
        "links": [
            {"kind": "hub",       "label": "Hub local",      "url": "https://hub.omar.paris/",          "status": "live"},
            {"kind": "hermesui",  "label": "Hermes UI",      "url": "http://100.79.68.6:9119/",         "status": "live"},
            {"kind": "monitoring","label": "Glances",        "url": "http://100.79.68.6:61208/",        "status": "live"},
            {"kind": "monitoring","label": "Dashy",          "url": "http://100.79.68.6:8084/",         "status": "tailnet"},
            {"kind": "monitoring","label": "Console Hetzner","url": "https://console.hetzner.cloud/",   "status": "live"},
        ],
    },
    "pan": {
        "label": "VPS-Pantheos",
        "role": "STUDIO",
        "role_color": "#7c3aed",
        "owner": "OA / Alex",
        "purpose": "Studio Pantheos : editing.alexgo.eu. Cible : H-Aurel + apps L1.",
        "tailnet": "",
        "links": [
            {"kind": "site",      "label": "editing.alexgo.eu", "url": "https://editing.alexgo.eu/",     "status": "live"},
            {"kind": "hub",       "label": "Hub local",         "url": "",                               "status": "todo"},
            {"kind": "hermesui",  "label": "Hermes UI",         "url": "",                               "status": "todo"},
            {"kind": "monitoring","label": "Glances",           "url": "",                               "status": "todo"},
            {"kind": "monitoring","label": "Console Hetzner",   "url": "https://console.hetzner.cloud/", "status": "live"},
        ],
    },
    "jab": {
        "label": "VPS-JAB",
        "role": "CLIENT",
        "role_color": "#16a34a",
        "owner": "Client JAB",
        "purpose": "Stack client JAB : facturation PennyLane, Maryse, Google MyBusiness.",
        "tailnet": "",
        "links": [
            {"kind": "hub",       "label": "Hub local",       "url": "",                               "status": "todo"},
            {"kind": "hermesui",  "label": "Hermes UI",       "url": "",                               "status": "todo"},
            {"kind": "monitoring","label": "Glances",         "url": "",                               "status": "todo"},
            {"kind": "monitoring","label": "Console Hetzner", "url": "https://console.hetzner.cloud/", "status": "live"},
        ],
    },
}

# ── Catalog by type ───────────────────────────────────────────────────────────
# Each type has options ordered best-first; default=True marks the OA standard choice.

CATALOG = [
    {
        "id": "infra",
        "name": "Infrastructure VPS",
        "icon": "server",
        "description": "Serveur dédié pour chaque client. Un VPS par client, isolé.",
        "options": [
            {"provider": "hetzner", "ref": "CAX21",  "name": "Hetzner CAX21 ARM",   "default": True,  "price_eur": 7.49,  "unit": "mois", "specs": "4 vCPU · 8 Go RAM · 80 Go NVMe",  "note": "Standard OA — ARM, bon rapport perf/prix"},
            {"provider": "hetzner", "ref": "CAX11",  "name": "Hetzner CAX11 ARM",   "default": False, "price_eur": 3.79,  "unit": "mois", "specs": "2 vCPU · 4 Go RAM · 40 Go NVMe",  "note": "Entrée de gamme — client solo léger"},
            {"provider": "hetzner", "ref": "CAX31",  "name": "Hetzner CAX31 ARM",   "default": False, "price_eur": 14.99, "unit": "mois", "specs": "8 vCPU · 16 Go RAM · 160 Go NVMe", "note": "Pack Pro — charge élevée"},
            {"provider": "hetzner", "ref": "CPX21",  "name": "Hetzner CPX21 Intel", "default": False, "price_eur": 6.39,  "unit": "mois", "specs": "3 vCPU · 4 Go RAM · 80 Go NVMe",  "note": "Alternative x86 si ARM incompatible"},
        ],
    },
    {
        "id": "domaine",
        "name": "Domaine & DNS",
        "icon": "globe",
        "description": "Enregistrement du nom de domaine client + gestion DNS.",
        "options": [
            {"provider": "ovh", "ref": "domain-fr",     "name": "OVH .fr",           "default": True,  "price_eur": 6.99,  "unit": "an",   "specs": None,                               "note": "Standard — clients France"},
            {"provider": "ovh", "ref": "domain-com",    "name": "OVH .com",          "default": False, "price_eur": 9.99,  "unit": "an",   "specs": None,                               "note": "Pour artisans avec ambition internationale"},
            {"provider": "ovh", "ref": "domain-paris",  "name": "OVH .paris",        "default": False, "price_eur": 14.99, "unit": "an",   "specs": None,                               "note": "Prestige Paris"},
            {"provider": "ovh", "ref": "domain-eu",     "name": "OVH .eu",           "default": False, "price_eur": 7.99,  "unit": "an",   "specs": None,                               "note": "Clients UE hors France"},
            {"provider": "infomaniak", "ref": "domain-ch", "name": "Infomaniak .ch", "default": False, "price_eur": 9.50,  "unit": "an",   "specs": None,                               "note": "Clients suisses uniquement"},
        ],
    },
    {
        "id": "email",
        "name": "Email professionnel",
        "icon": "mail",
        "description": "Boîte mail @domaine-client.fr. Option légère sans suite collaborative.",
        "options": [
            {"provider": "ovh", "ref": "email-pro",      "name": "OVH Email Pro",    "default": True,  "price_eur": 2.99,  "unit": "user/mois", "specs": "50 Go · IMAP/SMTP · calendrier basique", "note": "Standard — simple et fiable"},
            {"provider": "ovh", "ref": "mx-starter",     "name": "OVH MX Starter",  "default": False, "price_eur": 0.0,   "unit": "mois",      "specs": "1 Go · inclus avec domaine OVH",          "note": "Gratuit — test ou usage minimal"},
            {"provider": "ovh", "ref": "mx-pro-50",      "name": "OVH MX Plan Pro",  "default": False, "price_eur": 1.99,  "unit": "mois",      "specs": "50 Go · IMAP/SMTP",                       "note": "Budget serré sans suite"},
            {"provider": "infomaniak", "ref": "mail-ik", "name": "Infomaniak Mail",  "default": False, "price_eur": 1.25,  "unit": "user/mois", "specs": "25 Go · full IMAP · suisse",              "note": "Si client sensible à l'hébergement suisse"},
        ],
    },
    {
        "id": "suite",
        "name": "Suite collaborative (kSuite)",
        "icon": "apps",
        "description": "Email + Drive + Calendar + Meet + Docs + Chat. Tout-en-un Infomaniak.",
        "options": [
            {"provider": "infomaniak", "ref": "ksuite-1", "name": "kSuite 1",        "default": True,  "price_eur": 4.17,  "unit": "user/mois", "specs": "kMail 25 Go · kDrive 3 To · kMeet · kChat · kDocs · kBoard", "note": "Standard OA — facturation annuelle"},
            {"provider": "infomaniak", "ref": "ksuite-2", "name": "kSuite 2",        "default": False, "price_eur": 9.17,  "unit": "user/mois", "specs": "kMail 50 Go · kDrive 6 To · tout kSuite 1 + admin avancé",   "note": "Pour équipes > 5 ou besoins stockage élevés"},
        ],
    },
    {
        "id": "backup",
        "name": "Backup",
        "icon": "shield",
        "description": "Sauvegarde automatique du VPS client.",
        "options": [
            {"provider": "hetzner", "ref": "bkp-50",    "name": "Hetzner Volume 50 Go",      "default": True,  "price_eur": 1.19,  "unit": "mois", "specs": "50 Go NVMe · S3-compatible",        "note": "Standard — co-localisé avec le VPS"},
            {"provider": "infomaniak", "ref": "swiss-s", "name": "Infomaniak Swiss Backup S", "default": False, "price_eur": 4.99,  "unit": "mois", "specs": "200 Go · chiffré · data center CH", "note": "Option conformité / RGPD renforcé"},
        ],
    },
    {
        "id": "telephonie",
        "name": "Téléphonie",
        "icon": "phone",
        "description": "Numéro virtuel + SMS + voix pour le client. Full API, pas de contrat.",
        "options": [
            {"provider": "telnyx", "ref": "tel-local-fr", "name": "Telnyx n° local FR",    "default": True,  "price_eur": 0.92,  "unit": "mois",  "specs": "Numéro local France · SMS inclus",     "note": "Standard — achat + config 100% API"},
            {"provider": "telnyx", "ref": "tel-sms",      "name": "Telnyx SMS",            "default": True,  "price_eur": 0.004, "unit": "SMS",   "specs": "Entrant + sortant · ~0.004$/msg",      "note": "Pay-as-you-go · pas de minimum"},
            {"provider": "telnyx", "ref": "tel-tollfree", "name": "Telnyx n° vert (800)",  "default": False, "price_eur": 37.0,  "unit": "mois",  "specs": "TFN 800 · 12 mois engagement",         "note": "Option premium — artisans établis"},
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
        _tok = ""
        try:
            _tok = (Path.home() / ".config/oa-hub/machine-token").read_text().strip()
        except Exception:
            pass
        _hdrs = {"User-Agent": "OA-QG-probe/1.0"}
        if _tok and domain.endswith(".omar.paris"):
            _hdrs["X-OA-Token"] = _tok
        req = urllib.request.Request(url, headers=_hdrs)
        with urllib.request.urlopen(req, timeout=8, context=_SSL) as r:
            latency_ms = int((time.monotonic() - t0) * 1000)
            return {"status": "ok", "http_code": r.status, "latency_ms": latency_ms}
    except urllib.error.HTTPError as e:
        latency_ms = int((time.monotonic() - t0) * 1000)
        return {"status": "ok" if e.code < 500 else "error", "http_code": e.code, "latency_ms": latency_ms}
    except Exception:
        return {"status": "error", "http_code": None, "latency_ms": None}


def _paris_now() -> dt.datetime:
    if ZoneInfo:
        return dt.datetime.now(ZoneInfo("Europe/Paris"))
    return dt.datetime.now().astimezone()


def _day_bounds(day: str) -> tuple[int, int]:
    if ZoneInfo:
        tz = ZoneInfo("Europe/Paris")
        start = dt.datetime.fromisoformat(day).replace(tzinfo=tz)
    else:
        start = dt.datetime.fromisoformat(day).astimezone()
    end = start + dt.timedelta(days=1)
    return int(start.timestamp()), int(end.timestamp())


def hermes_daily_state(day: str) -> dict:
    base = {"sessions": 0, "messages": 0, "tool_calls": 0, "api_calls": 0, "by_source": {}, "db": str(STATE_DB), "error": None}
    if not STATE_DB.exists():
        base["error"] = "state_db_missing"
        return base
    start, end = _day_bounds(day)
    try:
        con = sqlite3.connect(STATE_DB)
        con.row_factory = sqlite3.Row
        row = con.execute(
            """
            select count(*) sessions,
                   coalesce(sum(message_count),0) messages,
                   coalesce(sum(tool_call_count),0) tool_calls,
                   coalesce(sum(api_call_count),0) api_calls
            from sessions where started_at >= ? and started_at < ?
            """,
            (start, end),
        ).fetchone()
        base.update({k: int(row[k] or 0) for k in ["sessions", "messages", "tool_calls", "api_calls"]})
        by_source = {}
        for r in con.execute(
            "select coalesce(source,'unknown') source, count(*) c from sessions where started_at >= ? and started_at < ? group by source",
            (start, end),
        ):
            by_source[r["source"]] = int(r["c"])
        base["by_source"] = by_source
    except Exception as exc:
        base["error"] = exc.__class__.__name__
    return base


def _ccusage_bin() -> str | None:
    for candidate in ["/home/omar/.npm-global/bin/ccusage", "ccusage"]:
        try:
            subprocess.check_output([candidate, "--version"], text=True, stderr=subprocess.DEVNULL, timeout=4)
            return candidate
        except Exception:
            continue
    return None


def ccusage_daily_state(day: str) -> dict:
    out = {"sessions_by_agent": {}, "daily": None, "error": None}
    exe = _ccusage_bin()
    if not exe:
        out["error"] = "ccusage_missing"
        return out
    try:
        raw_daily = subprocess.check_output([exe, "daily", "--json", "--since", day, "--until", day], text=True, stderr=subprocess.DEVNULL, timeout=45)
        daily_data = json.loads(raw_daily or "{}")
        rows = daily_data.get("daily", []) if isinstance(daily_data, dict) else []
        row = rows[-1] if rows else {}
        out["daily"] = {
            "total_cost_usd": round(float(row.get("totalCost", 0) or 0), 4),
            "total_tokens": int(row.get("totalTokens", 0) or 0),
            "agents": (row.get("metadata") or {}).get("agents", []),
            "models_used": row.get("modelsUsed", []),
        }
        raw_sessions = subprocess.check_output([exe, "session", "--json", "--since", day, "--until", day], text=True, stderr=subprocess.DEVNULL, timeout=60)
        sess_data = json.loads(raw_sessions or "{}")
        sessions = sess_data.get("session", []) if isinstance(sess_data, dict) else []
        by_agent = {}
        for r in sessions:
            if (r.get("metadata") or {}).get("lastActivity") != day:
                continue
            agent = r.get("agent") or "unknown"
            bucket = by_agent.setdefault(agent, {"sessions": 0, "cost_usd": 0.0, "tokens": 0})
            bucket["sessions"] += 1
            bucket["cost_usd"] += float(r.get("totalCost", 0) or 0)
            bucket["tokens"] += int(r.get("totalTokens", 0) or 0)
        out["sessions_by_agent"] = {k: {**v, "cost_usd": round(v["cost_usd"], 4)} for k, v in sorted(by_agent.items())}
    except Exception as exc:
        out["error"] = exc.__class__.__name__
    return out


def _iso_day(value: str | None) -> str:
    return (value or "")[:10]


def github_daily_activity(repo_slug: str, day: str) -> dict:
    base: dict[str, int | None] = {
        "issues_created": None,
        "issues_closed": None,
        "prs_created": None,
        "prs_merged": None,
        "build_runs": None,
        "build_success": None,
        "build_failed": None,
    }
    if not repo_slug or "/" not in repo_slug or not GH_TOKEN:
        return base

    # Use normal repo endpoints instead of GitHub Search API: Search is capped at
    # ~30 requests/min and test rebuilds can exhaust it. Repo endpoints use the
    # main REST quota and are enough for daily created/merged counts.
    issues = _gh_get(f"https://api.github.com/repos/{repo_slug}/issues?state=all&since={day}T00:00:00Z&per_page=100")
    if isinstance(issues, list):
        real_issues = [i for i in issues if "pull_request" not in i]
        base["issues_created"] = sum(1 for i in real_issues if _iso_day(i.get("created_at")) == day)
        base["issues_closed"] = sum(1 for i in real_issues if _iso_day(i.get("closed_at")) == day)

    prs = _gh_get(f"https://api.github.com/repos/{repo_slug}/pulls?state=all&sort=updated&direction=desc&per_page=100")
    if isinstance(prs, list):
        base["prs_created"] = sum(1 for p in prs if _iso_day(p.get("created_at")) == day)
        base["prs_merged"] = sum(1 for p in prs if _iso_day(p.get("merged_at")) == day)

    runs_url = f"https://api.github.com/repos/{repo_slug}/actions/runs?per_page=100&created={urllib.parse.quote('>='+day)}"
    runs = _gh_get(runs_url)
    if isinstance(runs, dict) and isinstance(runs.get("workflow_runs"), list):
        wr = runs["workflow_runs"]
        base["build_runs"] = len(wr)
        base["build_success"] = sum(1 for r in wr if r.get("conclusion") == "success")
        base["build_failed"] = sum(1 for r in wr if r.get("conclusion") in {"failure", "cancelled", "timed_out"})
    return base


def local_build_ledger(day: str) -> dict:
    path = BUILD_LEDGER_DIR / f"{day}.jsonl"
    rows = []
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                rows.append(json.loads(line))
            except Exception:
                continue
    return {
        "path": str(path),
        "count": len(rows),
        "success": sum(1 for r in rows if r.get("status") == "success"),
        "failure": sum(1 for r in rows if r.get("status") == "failure"),
        "blocked": sum(1 for r in rows if r.get("status") == "blocked"),
        "recent": rows[-12:],
    }


def daily_ledger(data: dict, built_at: str) -> dict:
    day = _paris_now().date().isoformat()
    repos = []
    totals = {
        "issues_created": 0,
        "issues_closed": 0,
        "prs_created": 0,
        "prs_merged": 0,
        "build_runs": 0,
        "build_success": 0,
        "build_failed": 0,
        "unknown_fields": 0,
    }
    for item in data.get("items", []):
        repo = item.get("repo", "")
        activity = github_daily_activity(repo, day) if repo else {}
        for k in ["issues_created", "issues_closed", "prs_created", "prs_merged", "build_runs", "build_success", "build_failed"]:
            if activity.get(k) is None:
                totals["unknown_fields"] += 1
            else:
                totals[k] += int(activity.get(k) or 0)
        repos.append({
            "id": item.get("id"),
            "name": item.get("name"),
            "repo": repo,
            "health": item.get("health", {}),
            "git": item.get("git", {}),
            "github_open": item.get("github", {}),
            "activity": activity,
        })
    hermes = hermes_daily_state(day)
    cc = ccusage_daily_state(day)
    builds = local_build_ledger(day)
    totals["local_build_records"] = builds["count"]
    alerts = []
    dirty = [r for r in repos if (r.get("git") or {}).get("dirty")]
    if dirty:
        alerts.append({"level": "warning", "code": "DIRTY_REPOS", "message": f"{len(dirty)} repo(s) locaux dirty dans le registry."})
    if totals["build_runs"] == 0 and builds["count"] == 0:
        alerts.append({"level": "warning", "code": "NO_BUILDS_RECORDED", "message": "Aucun build GitHub Actions ou ledger local détecté aujourd'hui."})
    session_total = int(hermes.get("sessions", 0) or 0) + sum(int(v.get("sessions", 0)) for v in cc.get("sessions_by_agent", {}).values())
    if session_total >= 10 and totals["prs_created"] == 0:
        alerts.append({"level": "warning", "code": "SESSIONS_WITHOUT_PRS", "message": "Beaucoup de sessions détectées mais aucune PR créée aujourd'hui."})
    if totals["prs_created"] > 0 and totals["prs_merged"] == 0:
        alerts.append({"level": "info", "code": "PRS_NOT_MERGED", "message": "PRs créées aujourd'hui mais aucune PR mergée détectée."})
    return {
        "date": day,
        "generated_at": built_at,
        "version": VERSION,
        "sessions": {"hermes": hermes, "ccusage": cc},
        "github_totals": totals,
        "local_builds": builds,
        "repos": repos,
        "alerts": alerts,
    }


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


def _vault_env() -> dict:
    """Vault env for unattended builds.

    Cron/systemd jobs may inherit no token, or a stale VAULT_TOKEN. The local
    root token file is the operational fallback on this VPS; never print it.
    """
    env = {**os.environ, "VAULT_ADDR": "http://127.0.0.1:8202"}
    token_file = Path.home() / ".vault-token"
    if token_file.exists():
        try:
            token = token_file.read_text(encoding="utf-8").strip()
        except Exception:
            token = ""
        if token:
            env["VAULT_TOKEN"] = token
    return env


def _vault_read(path: str) -> dict:
    try:
        raw = subprocess.check_output(
            ["/usr/bin/vault", "kv", "get", "-format=json", path],
            text=True, stderr=subprocess.DEVNULL,
            env=_vault_env(),
        )
        return json.loads(raw).get("data", {}).get("data", {})
    except Exception:
        return {}


def _ovh_get(path: str, creds: dict) -> object:
    import hashlib
    ak  = creds.get("OVH_APPLICATION_KEY", "")
    as_ = creds.get("OVH_APPLICATION_SECRET", "")
    ck  = creds.get("OVH_CONSUMER_KEY", "")
    if not (ak and as_ and ck):
        return None
    url = "https://eu.api.ovh.com/1.0" + path
    ts  = str(int(time.time()))
    sig = "$1$" + hashlib.sha1(f"{as_}+{ck}+GET+{url}++{ts}".encode()).hexdigest()
    req = urllib.request.Request(url, headers={
        "X-Ovh-Application": ak, "X-Ovh-Consumer": ck,
        "X-Ovh-Timestamp": ts, "X-Ovh-Signature": sig, "Accept": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=8) as r:
            return json.loads(r.read())
    except Exception:
        return None


def ovh_live(creds: dict) -> dict:
    domains = _ovh_get("/domain", creds) or []
    email_domains = _ovh_get("/email/domain", creds) or []
    email_with_accounts = []
    for d in email_domains:
        accounts = _ovh_get(f"/email/domain/{d}/account", creds)
        if isinstance(accounts, list) and accounts:
            email_with_accounts.append({"domain": d, "count": len(accounts)})
    return {
        "domains": sorted(domains) if isinstance(domains, list) else [],
        "email_domains_with_accounts": email_with_accounts,
    }


# ── Provider API probes ───────────────────────────────────────────────────────
# Each probe reads its key from Vault and hits a lightweight read-only endpoint.
# Runs at build time only (cron, no LLM tokens, invisible). Returns:
#   "ok"          — key present and API responds
#   "key_missing" — no key in Vault yet
#   "error"       — key present but API rejects / unreachable

def _http_status(url: str, headers: dict, timeout: int = 6) -> int | None:
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=_SSL) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code
    except Exception:
        return None


def probe_ovh() -> str:
    creds = _vault_read("secret/integrations/ovh")
    if not creds.get("OVH_CONSUMER_KEY"):
        return "key_missing"
    return "ok" if _ovh_get("/me", creds) else "error"


def probe_telnyx() -> str:
    creds = _vault_read("secret/integrations/telnyx")
    key = creds.get("TELNYX_API_KEY", "")
    if not key:
        return "key_missing"
    code = _http_status("https://api.telnyx.com/v2/balance", {"Authorization": f"Bearer {key}"})
    return "ok" if code == 200 else "error"


def probe_hetzner() -> str:
    creds = _vault_read("secret/integrations/hetzner/test")
    key = creds.get("HETZNER_API_TOKEN") or creds.get("HETZNER_TOKEN") or creds.get("HCLOUD_TOKEN", "")
    if not key:
        return "key_missing"
    code = _http_status("https://api.hetzner.cloud/v1/servers?per_page=1", {"Authorization": f"Bearer {key}"})
    return "ok" if code == 200 else "error"


def probe_infomaniak() -> str:
    creds = _vault_read("secret/integrations/infomaniak")
    key = creds.get("INFOMANIAK_API_TOKEN") or creds.get("INFOMANIAK_TOKEN") or creds.get("IK_TOKEN", "")
    if not key:
        return "key_missing"
    code = _http_status("https://api.infomaniak.com/1/profile", {"Authorization": f"Bearer {key}"})
    return "ok" if code == 200 else "error"


PROVIDER_PROBES = {
    "ovh": probe_ovh,
    "telnyx": probe_telnyx,
    "hetzner": probe_hetzner,
    "infomaniak": probe_infomaniak,
}


def probe_all_providers() -> dict:
    out = {}
    for pid, fn in PROVIDER_PROBES.items():
        try:
            out[pid] = fn()
        except Exception:
            out[pid] = "error"
    return out


def hetzner_fleet() -> list:
    """Live VPS fleet from Hetzner API, merged with VPS_META. No tokens, build-time."""
    creds = _vault_read("secret/integrations/hetzner/test")
    key = creds.get("HCLOUD_TOKEN") or creds.get("HETZNER_API_TOKEN") or creds.get("HETZNER_TOKEN", "")
    if not key:
        return []
    req = urllib.request.Request(
        "https://api.hetzner.cloud/v1/servers",
        headers={"Authorization": f"Bearer {key}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=8) as r:
            data = json.loads(r.read())
    except Exception:
        return []

    fleet = []
    for s in data.get("servers", []):
        name = s.get("name", "")
        st = s.get("server_type", {}) or {}
        dc = s.get("datacenter", {}) or {}
        loc = dc.get("location", {}) or {}
        img = s.get("image") or {}
        pn = (s.get("public_net", {}) or {}).get("ipv4", {}) or {}
        # match metadata by substring
        meta = {}
        for kkey, m in VPS_META.items():
            if kkey in name:
                meta = m
                break
        # monthly price for this server's location
        price = None
        for p in st.get("prices", []):
            if p.get("location") == loc.get("name"):
                try:
                    price = round(float(p.get("price_monthly", {}).get("gross", 0)), 2)
                except Exception:
                    price = None
        out_traffic = s.get("outgoing_traffic") or 0
        inc_traffic = s.get("included_traffic") or 0
        fleet.append({
            "name": name,
            "label": meta.get("label", name),
            "role": meta.get("role", "—"),
            "role_color": meta.get("role_color", "#6b7280"),
            "owner": meta.get("owner", "—"),
            "purpose": meta.get("purpose", ""),
            "links": meta.get("links", []),
            "tailnet": meta.get("tailnet", ""),
            "id": s.get("id"),
            "status": s.get("status", "?"),
            "type": st.get("name", "?"),
            "vcpu": st.get("cores"),
            "ram_gb": int(st.get("memory", 0)) if st.get("memory") else None,
            "disk_gb": st.get("disk"),
            "ip": pn.get("ip", ""),
            "datacenter": dc.get("name", ""),
            "location": f'{loc.get("city","")}, {loc.get("country","")}'.strip(", "),
            "os": img.get("name") or img.get("description") or "?",
            "created": (s.get("created") or "")[:10],
            "price_eur": price,
            "backups": "on" if s.get("backup_window") else "off",
            "traffic_out_gb": round(out_traffic / 1e9, 1),
            "traffic_inc_tb": round(inc_traffic / 1e12, 1),
        })
    # order: CORE, STUDIO, CLIENT, then others
    order = {"CORE OA": 0, "STUDIO": 1, "CLIENT": 2}
    fleet.sort(key=lambda v: order.get(v["role"], 9))
    return fleet


def _read_var_json(name: str) -> dict:
    """Read QG generated inputs without collecting new data.

    Runtime crons normally write ROOT/var/*.json. In clean worktrees those files are
    absent, so build-time pages fall back to the already-published public/api
    snapshots committed in the repo. This keeps app pages factual while respecting
    the issue #26 boundary: no extra API calls or fresh collection for detail pages.
    """
    for path in (ROOT / "var" / name, PUBLIC / "api" / name):
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
    return {}


def _read_existing_daily_ledgers(limit: int = 7) -> list[dict]:
    """Return existing daily-ledger snapshots from public/api (newest first)."""
    index = PUBLIC / "api" / "daily-ledger" / "index.json"
    out: list[dict] = []
    try:
        payload_index = json.loads(index.read_text(encoding="utf-8"))
    except Exception:
        payload_index = {}
    for item in payload_index.get("items", []) if isinstance(payload_index, dict) else []:
        if isinstance(item, dict) and item.get("date"):
            out.append(item)
    # Older builds only expose snapshot files; include them if the index is thin.
    ledger_dir = PUBLIC / "api" / "daily-ledger"
    if ledger_dir.exists():
        for path in sorted(ledger_dir.glob("*.json"), reverse=True):
            if path.name == "index.json":
                continue
            try:
                item = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if isinstance(item, dict) and item.get("date"):
                out.append(item)
    dedup: dict[str, dict] = {}
    for item in out:
        dedup.setdefault(str(item.get("date")), item)
    return [dedup[k] for k in sorted(dedup.keys(), reverse=True)[:limit]]


def _merge_daily_ledgers(current: dict, previous: list[dict], limit: int = 7) -> list[dict]:
    dedup: dict[str, dict] = {}
    for item in previous:
        if isinstance(item, dict) and item.get("date"):
            dedup[str(item["date"])] = item
    if isinstance(current, dict) and current.get("date"):
        dedup[str(current["date"])] = current
    return [dedup[k] for k in sorted(dedup.keys(), reverse=True)[:limit]]


def payload(built_at: str) -> dict:
    # Boucle d'auto-amélioration (10 juin 2026) : le triage quotidien remplace
    # le `next` codé en dur ; vps.json alimente la vue alignement VPS Hermes OA.
    triage = _read_var_json("triage.json")
    vps = _read_var_json("vps.json")
    items = []
    for item in ITEMS:
        enriched: dict = dict(item)
        enriched["git"] = git_state(item["path"])
        enriched["github"] = github_state(item.get("repo", ""))
        enriched["health"] = health_probe(item["domain"])
        t = (triage.get("apps") or {}).get(item["id"])
        if t and t.get("next"):
            enriched["next"] = t["next"]
            enriched["triage"] = {k: t.get(k) for k in ("p0", "p1", "p2", "top")}
        # Sources mesurées depuis l'actif local. Les valeurs codées dans ITEMS
        # documentent l'intention produit, mais ne doivent pas être affichées
        # comme des faits si le fichier source réel est absent.
        asset_dir = ACTIFS / item["path"]
        version_file = asset_dir / "VERSION"
        enriched["version_source"] = "unmeasured"
        enriched["version"] = "version non mesurée"
        try:
            v = version_file.read_text(encoding="utf-8").strip()
            if v:
                enriched["version"] = v if v[:1].upper() in ("V", "P") else f"V{v}"
                enriched["version_source"] = "VERSION"
        except Exception:
            pass
        enriched["has_contract_source"] = (asset_dir / "CONTRACT.md").exists()
        enriched["has_changelog_source"] = (asset_dir / "CHANGELOG.md").exists()
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
    # Live provider API status — probed at build time (cron, no tokens, invisible)
    statuses = probe_all_providers()
    providers = {}
    for pid, p in PROVIDERS.items():
        providers[pid] = {**p, "api_status": statuses.get(pid, "error")}

    # OVH live data only if its API is reachable
    live = {}
    if statuses.get("ovh") == "ok":
        live["ovh"] = ovh_live(_vault_read("secret/integrations/ovh"))
    else:
        live["ovh"] = {"domains": [], "email_domains_with_accounts": []}

    fleet = hetzner_fleet()
    return {
        "version": VERSION, "domain": DOMAIN, "built_at": built_at,
        "items": items, "counts": counts,
        "catalog": CATALOG, "providers": providers, "live": live,
        "fleet": fleet,
        "vps": vps,
        "triage": {"built_at": triage.get("built_at"), "llm_used": triage.get("llm_used"),
                   "top3": triage.get("top3", [])},
    }


# ── HTML layout ───────────────────────────────────────────────────────────────

TAILWIND = "https://cdn.tailwindcss.com"
FONTS    = "https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap"

NAV_ITEMS = [
    ("/",             "registry",    "Registry",    'M3.75 12h16.5m-16.5 3.75h16.5M3.75 19.5h16.5M5.625 4.5h12.75a1.875 1.875 0 0 1 0 3.75H5.625a1.875 1.875 0 0 1 0-3.75Z'),
    ("/ops/",         "ops",         "Ops",         'M3 13.125C3 12.504 3.504 12 4.125 12h2.25c.621 0 1.125.504 1.125 1.125v6.75C7.5 20.496 6.996 21 6.375 21h-2.25A1.125 1.125 0 0 1 3 19.875v-6.75ZM9.75 8.625c0-.621.504-1.125 1.125-1.125h2.25c.621 0 1.125.504 1.125 1.125v11.25c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 0 1-1.125-1.125V8.625ZM16.5 4.125C16.5 3.504 17.004 3 17.625 3h2.25C20.496 3 21 3.504 21 4.125v15.75c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 0 1-1.125-1.125V4.125Z'),
    ("/clients/",     "clients",     "Clients",     'M20.25 14.15v4.25c0 1.094-.787 2.036-1.872 2.18-2.087.277-4.216.42-6.378.42s-4.291-.143-6.378-.42c-1.085-.144-1.872-1.086-1.872-2.18v-4.25m16.5 0a2.18 2.18 0 0 0 .75-1.661V8.706c0-1.081-.768-2.015-1.837-2.175a48.114 48.114 0 0 0-3.413-.387m4.5 8.006c-.194.165-.42.295-.673.38A23.978 23.978 0 0 1 12 15.75c-2.648 0-5.195-.429-7.577-1.22a2.016 2.016 0 0 1-.673-.38m0 0A2.18 2.18 0 0 1 3 12.489V8.706c0-1.081.768-2.015 1.837-2.175a48.111 48.111 0 0 1 3.413-.387m7.5 0V5.25A2.25 2.25 0 0 0 13.5 3h-3a2.25 2.25 0 0 0-2.25 2.25v.894m7.5 0a48.667 48.667 0 0 0-7.5 0M12 12.75h.008v.008H12v-.008Z'),
    ("/partenaires/", "partenaires", "Partenaires", 'M13.5 21v-7.5a.75.75 0 0 1 .75-.75h3a.75.75 0 0 1 .75.75V21m-4.5 0H2.36m11.14 0H18m0 0h3.64m-1.39 0V9.349M3.75 21V9.349m0 0a3.001 3.001 0 0 0 3.75-.615A2.993 2.993 0 0 0 9.75 9.75c.896 0 1.7-.393 2.25-1.016a2.993 2.993 0 0 0 2.25 1.016 2.993 2.993 0 0 0 2.25-1.015M3.75 9.349a3 3 0 0 0 3.75.616m-3.75-.616a3.001 3.001 0 0 1-.75-1.99V6h17.25v1.36a3 3 0 0 1-.75 1.99m0 0a2.993 2.993 0 0 1-2.25 1.016'),
    ("/decisions/",   "decisions",   "Décisions",   'M9.879 7.519c1.171-1.025 3.071-1.025 4.242 0 1.172 1.025 1.172 2.687 0 3.712-.203.179-.43.326-.67.442-.745.361-1.45.999-1.45 1.827v.75M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0Zm-9 5.25h.008v.008H12v-.008Z'),
    ("/builds/",      "builds",      "Builds",      'M6.429 9.75 2.25 12l4.179 2.25m0-4.5 5.571 3 5.571-3m-11.142 0L2.25 7.5 12 2.25l9.75 5.25-4.179 2.25m0 0L21.75 12l-4.179 2.25m0 0 4.179 2.25L12 21.75 2.25 16.5l4.179-2.25m11.142 0-5.571 3-5.571-3'),
    ("/changelog/",   "changelog",   "Changelog",   'M12 6v6h4.5m4.5 0a9 9 0 1 1-18 0 9 9 0 0 1 18 0Z'),
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
    # Dernier push réel (git) en heure de Paris — pour qu'Alex se repère (demande 14/06)
    try:
        import subprocess as _sp
        last_push = _sp.run(["git", "-C", str(ROOT), "log", "-1", "--format=%cd", "--date=format-local:%d/%m %Hh%M"],
                            capture_output=True, text=True, timeout=10,
                            env={**__import__("os").environ, "TZ": "Europe/Paris"}).stdout.strip() or "?"
    except Exception:
        last_push = "?"
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
    <div class="text-xs text-gray-400">Rebuild {escape(ts_short)} · <span title="dernier commit poussé">push {escape(last_push)}</span></div>
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

def page_registry(data: dict, pending_decisions: int = 0, builds_today: int = 0) -> str:
    items = data["items"]
    counts = data["counts"]

    # Tuiles d'action : décisions à trancher + builds du jour (liens dédiés)
    dec_accent = "text-amber-600" if pending_decisions else "text-gray-900"
    tiles = (
        '<div class="grid grid-cols-1 sm:grid-cols-2 gap-3 mb-3">'
        f'<a href="/decisions/" class="block bg-white rounded-xl border border-gray-200 px-4 py-3 hover:border-blue-300 hover:shadow-sm transition">'
        f'<div class="flex items-center justify-between"><div><div class="text-2xl font-bold {dec_accent}">{pending_decisions}</div>'
        f'<div class="text-xs text-gray-500 mt-0.5">Décisions en attente</div></div>'
        f'<span class="text-xs text-blue-500">Trancher →</span></div></a>'
        f'<a href="/builds/" class="block bg-white rounded-xl border border-gray-200 px-4 py-3 hover:border-blue-300 hover:shadow-sm transition">'
        f'<div class="flex items-center justify-between"><div><div class="text-2xl font-bold text-gray-900">{builds_today}</div>'
        f'<div class="text-xs text-gray-500 mt-0.5">Builds aujourd’hui</div></div>'
        f'<span class="text-xs text-blue-500">Voir →</span></div></a>'
        '</div>'
    )

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
            gh_html = f'<a href="https://github.com/{escape(repo)}/issues" class="text-xs text-gray-500 hover:text-blue-600">{iss} ouvertes</a>'
        elif iss is not None:
            gh_html = f'<span class="text-xs text-gray-500">{iss} ouvertes</span>'
        else:
            gh_html = '<span class="text-xs text-gray-300">—</span>'
        if prs is not None and repo:
            gh_html += f' <a href="https://github.com/{escape(repo)}/pulls" class="text-xs text-gray-500 hover:text-blue-600">{prs} PRs</a>'
        tri = item.get("triage")
        if tri and ((tri.get("p0") or 0) + (tri.get("p1") or 0)) > 0:
            gh_html += (f'<span class="text-xs"><span class="text-red-600 font-semibold">P0 {tri.get("p0", 0)}</span>'
                        f' · <span class="text-amber-600">P1 {tri.get("p1", 0)}</span></span>')

        # Git dirty
        dirty = git.get("dirty", False)
        git_pill = f'<span class="{"pill-warn" if dirty else "pill-ok"} inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium">{"dirty" if dirty else "clean"}</span>'

        # Scope badge
        scope_cls = "bg-blue-50 text-blue-700" if item["scope"] == "CORE OA" else "bg-violet-50 text-violet-700"

        rows += (
            f'<div class="grid md:grid-cols-[1fr_100px_110px_100px_100px] gap-2 px-4 py-3.5 border-b border-gray-100 last:border-0 items-start hover:bg-gray-50">'
            f'<div><div class="flex items-center gap-2 mb-0.5">'
            f'<a href="{_app_route(item)}" class="text-sm font-semibold text-gray-900 hover:text-blue-600 hover:underline">{escape(item["name"])}</a>'
            f'<span class="text-xs rounded px-1.5 py-0.5 {scope_cls}">{escape("Référentiel VPS Hermes OA" if item["scope"] == "VPS Hermes OA" else item["scope"])}</span>'
            f'</div>'
            f'<div class="text-xs text-gray-500 mb-1.5">{escape(item["role"])}</div>'
            + (f'<div class="text-xs font-medium text-amber-700 mb-1.5">→ {escape(item["next"])}</div>' if item.get("next") else '')
            + f'<div class="flex gap-2 flex-wrap">'
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

    header = '<div class="flex items-center justify-between mb-6"><h1 class="text-xl font-bold text-gray-900">Registry CORE OA</h1><span class="text-xs text-gray-400">Rebuild auto · 30 min · Référentiel VPS Hermes OA</span></div>'
    return header + tiles + stats + rows


def _app_route(item: dict) -> str:
    return f'/apps/{item.get("id", "")}/'


def _repo_short(repo_slug: str) -> str:
    return repo_slug.split("/", 1)[-1] if repo_slug else ""


def _health_html(h: dict) -> str:
    status = h.get("status")
    if status == "ok":
        lat = f' · {h["latency_ms"]}ms' if h.get("latency_ms") else ""
        return f'<span class="pill-ok inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium">{escape(str(h.get("http_code", "ok")))}{escape(lat)}</span>'
    if h.get("http_code"):
        return f'<span class="pill-warn inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium">{escape(str(h.get("http_code")))}</span>'
    return '<span class="pill-err inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium">down</span>'


def _metric(v) -> str:
    return "—" if v is None else str(v)


def _app_commits(app: dict, builds: dict, limit: int = 5) -> list[dict]:
    repo_short = _repo_short(app.get("repo", ""))
    commits: list[dict] = []
    if not repo_short:
        return commits
    for day in builds.get("days", []) or []:
        for repo in day.get("repos", []) or []:
            if repo.get("repo") == repo_short or repo.get("name") == app.get("name"):
                commits.extend(repo.get("commits", []) or [])
    return commits[:limit]


def _app_history(app: dict, ledgers: list[dict]) -> list[dict]:
    out: list[dict] = []
    for ledger in ledgers:
        for repo in ledger.get("repos", []) or []:
            if repo.get("id") == app.get("id"):
                out.append({"date": ledger.get("date"), "repo": repo})
                break
    return out[:7]


def page_app_detail(data: dict, app: dict, builds: dict, ledgers: list[dict]) -> str:
    repo = app.get("repo", "")
    gh = app.get("github", {}) or {}
    git = app.get("git", {}) or {}
    triage = app.get("triage", {}) or {}
    top = [t for t in triage.get("top", []) if t.get("prio") in ("P0", "P1")]
    top.sort(key=lambda t: (0 if t.get("prio") == "P0" else 1, int(t.get("number") or 0)))
    commits = _app_commits(app, builds)
    history = _app_history(app, ledgers)

    html = (
        '<div class="mb-5"><a href="/" class="text-xs text-blue-500 hover:underline">← Registry</a></div>'
        '<div class="bg-white rounded-2xl border border-gray-200 px-6 py-5 mb-6">'
        '<div class="flex flex-col md:flex-row md:items-start md:justify-between gap-4">'
        '<div>'
        f'<div class="text-xs font-semibold uppercase tracking-wide text-blue-600 mb-1">{escape(app.get("scope", ""))}</div>'
        f'<h1 class="text-2xl font-bold text-gray-900">{escape(app.get("name", ""))}</h1>'
        f'<p class="text-sm text-gray-600 mt-2 max-w-2xl">{escape(app.get("role", ""))}</p>'
        '</div>'
        '<div class="flex flex-wrap gap-2 md:justify-end">'
        f'<span class="text-xs font-mono bg-gray-100 rounded px-2 py-1 text-gray-700">{escape(app.get("version", ""))}</span>'
        f'{_health_html(app.get("health", {}) or {})}'
        f'<span class="{"pill-warn" if git.get("dirty") else "pill-ok"} inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium">{"dirty" if git.get("dirty") else "clean"}</span>'
        '</div></div>'
        '<div class="flex gap-3 flex-wrap mt-5 text-sm">'
        f'<a class="text-blue-600 hover:underline" href="https://{escape(app.get("domain", ""))}/">{escape(app.get("domain", ""))}</a>'
        + (f'<a class="text-blue-600 hover:underline" href="https://github.com/{escape(repo)}">GitHub</a>' if repo else '')
        + (f'<a class="text-blue-600 hover:underline" href="https://github.com/{escape(repo)}/blob/main/CONTRACT.md">CONTRACT</a>' if repo and app.get("has_contract_source") else '')
        + (f'<a class="text-blue-600 hover:underline" href="{escape(app.get("changelog", ""))}">Changelog</a>' if app.get("changelog") and app.get("has_changelog_source") else '')
        + '</div></div>'
    )

    html += '<div class="grid md:grid-cols-3 gap-4 mb-6">'
    html += f'<div class="bg-white rounded-xl border border-gray-200 px-4 py-3"><div class="text-xs text-gray-500">Issues ouvertes</div><div class="text-2xl font-bold text-gray-900">{escape(str(gh.get("open_issues") if gh.get("open_issues") is not None else "—"))}</div></div>'
    html += f'<div class="bg-white rounded-xl border border-gray-200 px-4 py-3"><div class="text-xs text-gray-500">PRs ouvertes</div><div class="text-2xl font-bold text-gray-900">{escape(str(gh.get("open_prs") if gh.get("open_prs") is not None else "—"))}</div></div>'
    html += f'<div class="bg-white rounded-xl border border-gray-200 px-4 py-3"><div class="text-xs text-gray-500">Head local</div><div class="text-sm font-mono text-gray-700 break-words mt-1">{escape(git.get("head") or "—")}</div></div>'
    html += '</div>'

    html += '<div class="grid lg:grid-cols-2 gap-6 mb-6">'
    html += '<section class="bg-white rounded-xl border border-gray-200 overflow-hidden"><div class="px-4 py-3 border-b border-gray-100"><h2 class="text-sm font-bold text-gray-900">P0/P1 du jour</h2><p class="text-xs text-gray-500">Source: triage QG existant, trié P0 puis P1.</p></div>'
    if top:
        for issue in top:
            badge = 'bg-red-50 text-red-700' if issue.get("prio") == "P0" else 'bg-amber-50 text-amber-700'
            html += (
                '<a class="block px-4 py-3 border-b border-gray-100 last:border-0 hover:bg-gray-50" '
                f'href="{escape(issue.get("url", "#"))}">'
                f'<span class="inline-flex rounded px-1.5 py-0.5 text-xs font-semibold {badge}">{escape(issue.get("prio", ""))}</span> '
                f'<span class="text-xs font-mono text-gray-400">#{escape(str(issue.get("number", "")))}</span> '
                f'<span class="text-sm text-gray-800">{escape(issue.get("title", ""))}</span></a>'
            )
    else:
        html += '<div class="px-4 py-5 text-sm text-gray-500">Aucun P0/P1 mesuré dans le triage publié.</div>'
    html += '</section>'

    html += '<section class="bg-white rounded-xl border border-gray-200 overflow-hidden"><div class="px-4 py-3 border-b border-gray-100"><h2 class="text-sm font-bold text-gray-900">Derniers commits</h2><p class="text-xs text-gray-500">Source: API builds QG / 7 jours.</p></div>'
    if commits:
        for c in commits:
            html += (
                '<div class="px-4 py-3 border-b border-gray-100 last:border-0">'
                f'<div class="flex gap-2 items-center"><span class="text-xs font-mono bg-gray-100 rounded px-1.5 py-0.5 text-gray-600">{escape(c.get("hash", ""))}</span>'
                f'<span class="text-xs text-gray-400">{escape(c.get("date", ""))}</span></div>'
                f'<div class="text-sm text-gray-800 mt-1">{escape(c.get("message", ""))}</div>'
                f'<div class="text-xs text-gray-400 mt-0.5">{escape(c.get("author", ""))}</div>'
                '</div>'
            )
    else:
        html += '<div class="px-4 py-5 text-sm text-gray-500">Aucun commit mesuré dans la fenêtre builds.</div>'
    html += '</section></div>'

    html += '<section class="bg-white rounded-xl border border-gray-200 overflow-hidden"><div class="px-4 py-3 border-b border-gray-100"><h2 class="text-sm font-bold text-gray-900">Historique 7 jours</h2><p class="text-xs text-gray-500">Source: daily-ledgers QG existants + ledger courant.</p></div>'
    if history:
        html += '<div class="grid md:grid-cols-[120px_1fr_1fr_1fr_1fr] gap-2 px-4 py-2 bg-gray-50 text-xs font-semibold uppercase tracking-wide text-gray-500"><span>Date</span><span>Health</span><span>Issues</span><span>PRs</span><span>Builds</span></div>'
        for row in history:
            r = row["repo"]
            act = r.get("activity", {}) or {}
            h = r.get("health", {}) or {}
            html += (
                '<div class="grid md:grid-cols-[120px_1fr_1fr_1fr_1fr] gap-2 px-4 py-3 border-t border-gray-100 text-sm">'
                f'<span class="font-mono text-gray-500">{escape(row.get("date", ""))}</span>'
                f'<span>{_health_html(h)}</span>'
                f'<span>{escape(_metric(act.get("issues_created")))} créées / {escape(_metric(act.get("issues_closed")))} fermées</span>'
                f'<span>{escape(_metric(act.get("prs_created")))} créées / {escape(_metric(act.get("prs_merged")))} mergées</span>'
                f'<span>{escape(_metric(act.get("build_runs")))} runs</span>'
                '</div>'
            )
    else:
        html += '<div class="px-4 py-5 text-sm text-gray-500">Aucun historique ledger disponible pour cette app.</div>'
    html += '</section>'
    return html


def _api_badge(status: str) -> str:
    labels = {
        "ok":          ("bg-green-50 text-green-700 border border-green-200",   "API OK"),
        "key_missing": ("bg-gray-100 text-gray-500 border border-gray-200",     "Clef à ajouter"),
        "error":       ("bg-red-50 text-red-700 border border-red-200",         "Erreur API"),
    }
    cls, label = labels.get(status, ("bg-gray-100 text-gray-500","?"))
    return f'<span class="inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium {cls}">{escape(label)}</span>'


def _provider_chip(provider_id: str, providers: dict) -> str:
    p = providers.get(provider_id, {})
    color = p.get("color", "#6b7280")
    name = p.get("name", provider_id)
    return f'<span class="inline-flex items-center rounded px-1.5 py-0.5 text-xs font-semibold text-white" style="background:{escape(color)}">{escape(name)}</span>'


def page_partenaires(data: dict) -> str:
    catalog  = data["catalog"]
    providers = data["providers"]
    live_ovh = data.get("live", {}).get("ovh", {})

    html = (
        '<div class="flex items-center justify-between mb-6">'
        '<div><h1 class="text-xl font-bold text-gray-900">Catalogue fournisseurs</h1>'
        '<p class="text-sm text-gray-500 mt-0.5">Briques disponibles pour provisionner un client. ★ = option OA par défaut.</p></div>'
        '</div>'
    )

    # ── Catalog by type ──
    for cat in catalog:
        options_html = ""
        for o in cat["options"]:
            is_default = o.get("default", False)
            price = o["price_eur"]
            unit = o.get("unit", "mois")
            price_str = "gratuit" if price == 0.0 else f'{price:.3g} €/{unit}'
            specs = escape(o["specs"]) if o.get("specs") else ""
            note = escape(o.get("note", ""))
            default_badge = '<span class="text-yellow-500 font-bold mr-1" title="Option OA par défaut">★</span>' if is_default else '<span class="mr-1 text-transparent">★</span>'
            row_cls = "bg-blue-50/30" if is_default else ""
            options_html += (
                f'<div class="flex items-start justify-between py-2.5 px-4 border-b border-gray-100 last:border-0 {row_cls} hover:bg-gray-50">'
                f'<div class="flex items-start gap-2">'
                f'<span class="mt-0.5">{default_badge}</span>'
                f'<div>'
                f'<div class="flex items-center gap-2 flex-wrap">'
                f'<span class="text-sm font-medium text-gray-900">{escape(o["name"])}</span>'
                f'{_provider_chip(o["provider"], providers)}'
                f'</div>'
                + (f'<div class="text-xs text-gray-400 mt-0.5">{specs}{"  · " + note if note else ""}</div>' if specs or note else "")
                + f'</div></div>'
                f'<div class="text-sm font-semibold text-gray-800 ml-4 shrink-0 whitespace-nowrap">{escape(price_str)}</div>'
                f'</div>'
            )

        html += (
            f'<div class="bg-white rounded-xl border border-gray-200 mb-4">'
            f'<div class="px-4 py-3 border-b border-gray-100 flex items-center justify-between">'
            f'<div><div class="text-sm font-bold text-gray-900">{escape(cat["name"])}</div>'
            f'<div class="text-xs text-gray-400 mt-0.5">{escape(cat["description"])}</div></div>'
            f'</div>'
            f'{options_html}'
            f'</div>'
        )

    # ── Providers API status ──
    html += '<div class="mt-6 mb-3"><h2 class="text-sm font-semibold text-gray-700">Statut API fournisseurs</h2></div>'
    html += '<div class="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-6">'
    for pid, p in providers.items():
        html += (
            f'<div class="bg-white rounded-xl border border-gray-200 px-3 py-3">'
            f'<div class="flex items-center gap-2 mb-2">'
            f'<div class="w-7 h-7 rounded text-white text-xs font-bold flex items-center justify-center" style="background:{escape(p["color"])}">{escape(p["logo"])}</div>'
            f'<span class="text-sm font-medium text-gray-900">{escape(p["name"])}</span>'
            f'</div>'
            f'{_api_badge(p["api_status"])}'
            f'<div class="text-xs text-gray-300 font-mono mt-1 truncate">{escape(p["vault_key"])}</div>'
            f'</div>'
        )
    html += '</div>'

    # ── OVH live data ──
    domains = live_ovh.get("domains", [])
    email_accounts = live_ovh.get("email_domains_with_accounts", [])
    if domains:
        html += (
            f'<div class="bg-white rounded-xl border border-gray-200 mb-4">'
            f'<div class="px-4 py-3 border-b border-gray-100">'
            f'<div class="text-sm font-bold text-gray-900">OVH — {len(domains)} domaines live</div>'
            f'<div class="text-xs text-gray-400">Lus depuis l\'API OVH au dernier build</div>'
            f'</div>'
            f'<div class="px-4 py-3 flex flex-wrap gap-2">'
            + "".join(f'<span class="text-xs bg-blue-50 text-blue-700 rounded px-2 py-0.5 font-mono">{escape(d)}</span>' for d in domains)
            + f'</div></div>'
        )
    if email_accounts:
        rows_em = "".join(
            f'<div class="flex items-center justify-between py-2 border-b border-gray-100 last:border-0">'
            f'<span class="text-sm font-mono text-gray-700">{escape(e["domain"])}</span>'
            f'<span class="text-xs text-gray-500">{e["count"]} compte(s)</span>'
            f'</div>'
            for e in email_accounts
        )
        html += (
            f'<div class="bg-white rounded-xl border border-gray-200">'
            f'<div class="px-4 py-3 border-b border-gray-100">'
            f'<div class="text-sm font-bold text-gray-900">OVH — domaines email avec comptes actifs</div>'
            f'</div><div class="px-4 py-1">{rows_em}</div></div>'
        )

    return html


def _link_status_dot(status: str) -> str:
    colors = {"live": "#22c55e", "tailnet": "#3b82f6", "todo": "#d1d5db"}
    return colors.get(status, "#d1d5db")


def page_clients(data: dict) -> str:
    fleet = data.get("fleet", [])
    html = (
        '<div class="flex items-center justify-between mb-6">'
        '<div><h1 class="text-xl font-bold text-gray-900">Clients & VPS</h1>'
        '<p class="text-sm text-gray-500 mt-0.5">Flotte live Hetzner. Données rafraîchies au rebuild (30 min).</p></div>'
        '</div>'
    )

    # Alignement des 3 VPS sur le standard VPS Hermes OA (vps-doctor quotidien)
    vps_data = data.get("vps") or {}
    if vps_data.get("vps"):
        html += '<h2 class="text-sm font-semibold text-gray-700 mb-3">Alignement standard VPS Hermes OA <span class="text-xs text-gray-400 font-normal">(oa-doctor quotidien · OmarTop P0→P6)</span></h2>'
        html += '<div class="grid md:grid-cols-3 gap-4 mb-8">'
        for v in vps_data["vps"]:
            if str(v.get("status", "")).startswith("measured"):
                sysd = v.get("system", {})
                doctor = v.get("doctor", {})
                alerts = sysd.get("alerts") or []
                score = f'{doctor.get("score_pct")}%' if doctor.get("score_pct") is not None else "—"
                pill = (f'<span class="pill-warn rounded-full px-2 py-0.5 text-xs font-medium">{len(alerts)} alerte(s)</span>'
                        if alerts else '<span class="pill-ok rounded-full px-2 py-0.5 text-xs font-medium">sain</span>')
                detail = escape("; ".join(alerts[:2])) if alerts else f'disque {escape(str(sysd.get("disk_root") or "?"))} · swap {escape(str(sysd.get("swap_pct")))}%'
                html += (
                    f'<div class="bg-white rounded-xl border border-gray-200 px-4 py-3">'
                    f'<div class="flex items-center justify-between mb-1"><span class="text-sm font-semibold text-gray-900">{escape(v["name"])}</span>{pill}</div>'
                    f'<div class="text-2xl font-bold text-gray-900">{escape(score)}<span class="text-xs text-gray-400 font-normal"> oa-doctor</span></div>'
                    f'<div class="text-xs text-gray-500 mt-1">{detail}</div>'
                    f'</div>'
                )
            else:
                html += (
                    f'<div class="bg-gray-50 rounded-xl border border-dashed border-gray-300 px-4 py-3">'
                    f'<div class="text-sm font-semibold text-gray-500 mb-1">{escape(v["name"])}</div>'
                    f'<div class="text-xs text-gray-400">{escape(v.get("note", "pending"))}</div>'
                    f'</div>'
                )
        html += '</div>'

    if not fleet:
        return html + '<div class="bg-yellow-50 border border-yellow-200 rounded-xl px-5 py-4 text-sm text-yellow-700">Flotte Hetzner indisponible — clef API absente ou en erreur.</div>'

    # Fleet summary bar
    total_cost = sum(v["price_eur"] or 0 for v in fleet)
    running = sum(1 for v in fleet if v["status"] == "running")
    html += (
        f'<div class="grid grid-cols-3 gap-3 mb-6">'
        f'<div class="bg-white rounded-xl border border-gray-200 px-4 py-3"><div class="text-2xl font-bold text-gray-900">{len(fleet)}</div><div class="text-xs text-gray-500 mt-0.5">VPS</div></div>'
        f'<div class="bg-white rounded-xl border border-gray-200 px-4 py-3"><div class="text-2xl font-bold text-gray-900">{running}<span class="text-gray-400 text-sm font-normal">/{len(fleet)}</span></div><div class="text-xs text-gray-500 mt-0.5">Running</div></div>'
        f'<div class="bg-white rounded-xl border border-gray-200 px-4 py-3"><div class="text-2xl font-bold text-gray-900">{total_cost:.0f}<span class="text-gray-400 text-sm font-normal"> €/mois</span></div><div class="text-xs text-gray-500 mt-0.5">Coût flotte</div></div>'
        f'</div>'
    )

    # 2-column gallery
    html += '<div class="grid md:grid-cols-2 gap-4">'
    for v in fleet:
        status_dot = "#22c55e" if v["status"] == "running" else "#ef4444"
        # 10 info rows
        infos = [
            ("Rôle", f'<span class="rounded px-1.5 py-0.5 text-xs font-semibold text-white" style="background:{v["role_color"]}">{escape(v["role"])}</span>'),
            ("Owner", escape(v["owner"])),
            ("IP publique", f'<span class="font-mono text-xs">{escape(v["ip"])}</span>'),
            ("Type", f'{escape(v["type"])} · {v["vcpu"]} vCPU / {v["ram_gb"]} Go'),
            ("Disque", f'{v["disk_gb"]} Go'),
            ("Datacenter", escape(v["location"])),
            ("OS", escape(v["os"])),
            ("Créé le", escape(v["created"])),
            ("Coût", f'{v["price_eur"]:.2f} €/mois' if v["price_eur"] else "—"),
            ("Backups", f'<span class="{"text-green-600" if v["backups"]=="on" else "text-gray-400"}">{v["backups"]}</span>'),
            ("Trafic sortant", f'{v["traffic_out_gb"]} Go / {v["traffic_inc_tb"]} To inclus'),
        ]
        infos_html = "".join(
            f'<div class="flex items-center justify-between py-1.5 border-b border-gray-50 last:border-0">'
            f'<span class="text-xs text-gray-400">{escape(label)}</span>'
            f'<span class="text-sm text-gray-700 text-right">{val}</span></div>'
            for label, val in infos
        )

        # links: hub, hermesui, monitoring
        links_html = ""
        for lk in v.get("links", []):
            dot = _link_status_dot(lk["status"])
            if lk["status"] == "todo" or not lk["url"]:
                links_html += (
                    f'<span class="inline-flex items-center gap-1.5 text-xs text-gray-400 bg-gray-50 rounded-lg px-2.5 py-1.5 border border-gray-100">'
                    f'<span class="w-1.5 h-1.5 rounded-full" style="background:{dot}"></span>{escape(lk["label"])} <span class="text-gray-300">à installer</span></span>'
                )
            else:
                links_html += (
                    f'<a href="{escape(lk["url"])}" target="_blank" class="inline-flex items-center gap-1.5 text-xs text-gray-700 hover:text-blue-600 bg-white rounded-lg px-2.5 py-1.5 border border-gray-200 hover:border-blue-300">'
                    f'<span class="w-1.5 h-1.5 rounded-full" style="background:{dot}"></span>{escape(lk["label"])}</a>'
                )

        html += (
            f'<div class="bg-white rounded-xl border border-gray-200 overflow-hidden">'
            f'<div class="px-5 py-4 border-b border-gray-100 flex items-center justify-between">'
            f'<div class="flex items-center gap-2">'
            f'<span class="w-2.5 h-2.5 rounded-full" style="background:{status_dot}"></span>'
            f'<div><div class="text-sm font-bold text-gray-900">{escape(v["label"])}</div>'
            f'<div class="text-xs text-gray-400 font-mono">{escape(v["name"])}</div></div>'
            f'</div>'
            f'<span class="text-xs text-gray-400">{escape(v["status"])}</span>'
            f'</div>'
            f'<div class="px-5 py-2.5 text-xs text-gray-500 border-b border-gray-50">{escape(v["purpose"])}</div>'
            f'<div class="px-5 py-2">{infos_html}</div>'
            f'<div class="px-5 py-3 border-t border-gray-100 flex flex-wrap gap-2">{links_html}</div>'
            f'</div>'
        )
    html += '</div>'
    return html


def _num(v) -> int:
    try:
        return int(v or 0)
    except Exception:
        return 0


def page_ops(ledger: dict) -> str:
    gh = ledger.get("github_totals", {})
    hermes = ledger.get("sessions", {}).get("hermes", {})
    cc = ledger.get("sessions", {}).get("ccusage", {})
    by_agent = cc.get("sessions_by_agent", {}) or {}
    cc_sessions = sum(_num(v.get("sessions")) for v in by_agent.values())
    cc_daily = cc.get("daily") or {}
    alerts = ledger.get("alerts", [])

    def card(label: str, value: str, sub: str = "") -> str:
        sub_html = f'<div class="text-xs text-gray-400 mt-1">{escape(sub)}</div>' if sub else ""
        return f'<div class="bg-white rounded-xl border border-gray-200 px-4 py-3"><div class="text-2xl font-bold text-gray-900">{escape(str(value))}</div><div class="text-xs text-gray-500 mt-0.5">{escape(label)}</div>{sub_html}</div>'

    html = (
        '<div class="flex items-center justify-between mb-6">'
        '<div><h1 class="text-xl font-bold text-gray-900">Ops quotidien</h1>'
        f'<p class="text-sm text-gray-500 mt-0.5">Ledger automatique du {escape(ledger.get("date", ""))} — sessions, issues, PRs, builds, anomalies.</p></div>'
        '<a href="/api/daily-ledger/index.json" class="text-xs text-blue-500 hover:underline">API ledger</a>'
        '</div>'
    )
    html += '<div class="grid grid-cols-2 lg:grid-cols-4 gap-3 mb-6">'
    html += card("Sessions Hermes", hermes.get("sessions", 0), f'{hermes.get("messages", 0)} messages · {hermes.get("tool_calls", 0)} tools')
    html += card("Sessions Claude/CLI", cc_sessions, ", ".join(f"{k}:{v.get('sessions',0)}" for k, v in by_agent.items()) or "ccusage")
    html += card("Issues créées", gh.get("issues_created", 0), f'{gh.get("issues_closed", 0)} fermées')
    html += card("PRs créées", gh.get("prs_created", 0), f'{gh.get("prs_merged", 0)} mergées')
    html += card("Builds", gh.get("build_runs", 0) + gh.get("local_build_records", 0), f'{gh.get("build_success", 0)} OK · {gh.get("build_failed", 0)} KO · {gh.get("local_build_records", 0)} locaux')
    html += card("Coût tokens", f'${cc_daily.get("total_cost_usd", 0):.2f}' if isinstance(cc_daily.get("total_cost_usd", 0), (int, float)) else "—", f'{cc_daily.get("total_tokens", 0)} tokens')
    html += card("Repos dirty", sum(1 for r in ledger.get("repos", []) if (r.get("git") or {}).get("dirty")), "statut local")
    html += card("Alertes", len(alerts), "warnings / infos")
    html += '</div>'

    if alerts:
        html += '<div class="space-y-2 mb-6">'
        for a in alerts:
            cls = "border-yellow-200 bg-yellow-50 text-yellow-800" if a.get("level") == "warning" else "border-blue-200 bg-blue-50 text-blue-800"
            html += f'<div class="rounded-xl border px-4 py-3 text-sm {cls}"><span class="font-semibold">{escape(a.get("code", "ALERT"))}</span> — {escape(a.get("message", ""))}</div>'
        html += '</div>'

    html += '<div class="bg-white rounded-xl border border-gray-200 overflow-hidden mb-6">'
    html += '<div class="px-4 py-3 border-b border-gray-100"><div class="text-sm font-bold text-gray-900">Repos core — activité du jour</div></div>'
    html += '<div class="grid grid-cols-[1fr_80px_80px_80px_80px_80px] gap-2 px-4 py-2 bg-gray-50 text-xs font-semibold text-gray-500 uppercase hidden md:grid"><span>Repo</span><span>Issues</span><span>PRs</span><span>Merges</span><span>Builds</span><span>Local</span></div>'
    for r in ledger.get("repos", []):
        act = r.get("activity", {}) or {}
        git = r.get("git", {}) or {}
        dirty = git.get("dirty", False)
        repo = r.get("repo") or "—"
        html += (
            f'<div class="grid md:grid-cols-[1fr_80px_80px_80px_80px_80px] gap-2 px-4 py-3 border-b border-gray-100 last:border-0 text-sm items-center">'
            f'<div><div class="font-semibold text-gray-900">{escape(r.get("name") or r.get("id") or "")}</div><div class="text-xs text-gray-400 font-mono">{escape(repo)}</div></div>'
            f'<div class="text-gray-700">{escape(str(act.get("issues_created", "—")))}</div>'
            f'<div class="text-gray-700">{escape(str(act.get("prs_created", "—")))}</div>'
            f'<div class="text-gray-700">{escape(str(act.get("prs_merged", "—")))}</div>'
            f'<div class="text-gray-700">{escape(str(act.get("build_runs", "—")))}</div>'
            f'<div><span class="{"pill-warn" if dirty else "pill-ok"} inline-flex rounded-full px-2 py-0.5 text-xs font-medium">{"dirty" if dirty else "clean"}</span></div>'
            f'</div>'
        )
    html += '</div>'

    local = ledger.get("local_builds", {})
    html += '<div class="bg-white rounded-xl border border-gray-200 px-4 py-3">'
    html += '<div class="text-sm font-bold text-gray-900 mb-1">Ledger builds local</div>'
    html += f'<div class="text-xs text-gray-400 font-mono mb-3">{escape(local.get("path", ""))}</div>'
    if local.get("recent"):
        for b in local.get("recent", []):
            html += f'<div class="text-xs text-gray-600 py-1 border-t border-gray-50"><span class="font-mono">{escape(b.get("repo", ""))}</span> · {escape(b.get("status", ""))} · {escape(b.get("command", ""))}</div>'
    else:
        html += '<div class="text-sm text-gray-500">Aucun build local enregistré aujourd’hui. Utiliser <code class="font-mono text-xs bg-gray-100 px-1 rounded">python3 scripts/record_build.py ...</code>.</div>'
    html += '</div>'
    return html


def page_decisions(decisions: list) -> str:
    """Boîte de décisions Alex (qg#27) — réponse = bouton → qg-api → déblocage kanban/issue."""
    api = "http://100.79.68.6:8097/api/decisions/answer"
    ouvertes = [q for q in decisions if q.get("statut") == "ouverte"]
    repondues = [q for q in decisions if q.get("statut") == "répondue"][-5:]
    html = (
        '<div class="flex items-center justify-between mb-6">'
        '<div><h1 class="text-xl font-bold text-gray-900">Décisions en attente</h1>'
        f'<p class="text-sm text-gray-500 mt-0.5">{len(ouvertes)} question(s) ouverte(s) — une réponse débloque le processus qui attend.</p></div></div>'
    )
    if not ouvertes:
        html += '<div class="bg-green-50 border border-green-200 rounded-xl px-5 py-4 text-sm text-green-700">Rien en attente — le système avance seul.</div>'
    groupes: dict = {}
    for q in ouvertes:
        groupes.setdefault(q.get("groupe", "divers"), []).append(q)
    for groupe, qs in groupes.items():
        html += f'<h2 class="text-sm font-semibold text-gray-700 mt-6 mb-2 uppercase tracking-wide">{escape(groupe)}</h2>'
        for q in qs:
            qid = escape(q["id"])
            html += '<div class="bg-white rounded-xl border border-gray-200 px-5 py-4 mb-3" id="card-' + qid + '">'
            html += f'<div class="text-sm font-medium text-gray-900 mb-1">{escape(q["texte"])}</div>'
            if q.get("contexte"):
                html += f'<div class="text-xs text-gray-500 mb-2">{escape(q["contexte"])}</div>'
            if q.get("blocked_ref"):
                html += f'<div class="text-xs text-amber-600 mb-2">⏸ bloque : {escape(q["blocked_ref"])}</div>'
            if q.get("type") == "fermée":
                # Feedback Alex 10 juin : possibilité d'ajouter un complément à une réponse fermée
                html += '<div class="flex gap-2 flex-wrap mb-2">'
                for opt in q.get("options", []):
                    html += (f'<button onclick="answerClosed(\'{qid}\', \'{escape(opt)}\')" '
                             'class="px-3 py-1.5 rounded-lg bg-blue-600 text-white text-xs font-medium hover:bg-blue-700">'
                             f'{escape(opt)}</button>')
                html += '</div>'
                html += (f'<input id="compl-{qid}" type="text" placeholder="Complément optionnel (token, précision…) — ajouté à ta réponse" '
                         'class="w-full border border-gray-200 rounded-lg px-3 py-1.5 text-xs text-gray-600">')
            else:
                html += (f'<div class="flex gap-2"><input id="in-{qid}" type="text" placeholder="Ta réponse…" '
                         'class="flex-1 border border-gray-300 rounded-lg px-3 py-1.5 text-sm">'
                         f'<button onclick="answer(\'{qid}\', document.getElementById(\'in-{qid}\').value)" '
                         'class="px-3 py-1.5 rounded-lg bg-blue-600 text-white text-xs font-medium hover:bg-blue-700">Envoyer</button></div>')
            html += '</div>'
    if repondues:
        html += '<h2 class="text-sm font-semibold text-gray-400 mt-8 mb-2">Dernières réponses</h2>'
        for q in reversed(repondues):
            html += (f'<div class="text-xs text-gray-500 mb-1">✓ <span class="text-gray-700">{escape(q["texte"])}</span>'
                     f' → <span class="font-medium text-gray-900">{escape(str(q.get("reponse")))}</span>'
                     f' <span class="text-gray-400">({escape(q.get("deblocage", ""))})</span></div>')
    html += ('<script>function answerClosed(id, opt){ const c = document.getElementById("compl-"+id); '
             'answer(id, opt + (c && c.value.trim() ? " — " + c.value.trim() : "")); } '
             'async function answer(id, val){ if(!val||!val.trim()){return;} '
             f'const r = await fetch("{api}", {{method:"POST", headers:{{"content-type":"application/json"}}, '
             'body: JSON.stringify({id:id, answer:val})}); '
             'const c = document.getElementById("card-"+id); '
             'if(r.ok){ c.innerHTML = \'<div class="text-sm text-green-700">✓ Réponse envoyée — \' + val + \' (processus débloqué)</div>\'; }'
             'else{ c.innerHTML += \'<div class="text-xs text-red-600 mt-2">Erreur — réessaie ou réponds en session.</div>\'; } }</script>')
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


_FR_MONTHS = ["janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc."]


def _fr_day(iso: str) -> str:
    try:
        y, m, d = (int(x) for x in iso.split("-"))
        return f"{d} {_FR_MONTHS[m - 1]} {y}"
    except Exception:
        return iso


def page_builds(builds: dict) -> str:
    t = builds.get("totals", {}) or {}
    today = builds.get("today", "")
    days = builds.get("days", []) or []

    html = (
        '<div class="flex items-center justify-between mb-6">'
        '<div><h1 class="text-xl font-bold text-gray-900">Builds du jour</h1>'
        f'<p class="text-sm text-gray-500 mt-0.5">Commits collectés sur les repos CORE OA — {escape(_fr_day(today))} et 7 derniers jours.</p></div>'
        '<a href="/api/builds.json" class="text-xs text-blue-500 hover:underline">API builds</a>'
        '</div>'
    )

    # Compteurs
    html += '<div class="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-6">'
    html += f'<div class="bg-white rounded-xl border border-gray-200 px-4 py-3"><div class="text-2xl font-bold text-gray-900">{t.get("today", 0)}</div><div class="text-xs text-gray-500 mt-0.5">Builds aujourd’hui</div></div>'
    html += f'<div class="bg-white rounded-xl border border-gray-200 px-4 py-3"><div class="text-2xl font-bold text-gray-900">{t.get("repos_today", 0)}<span class="text-gray-400 text-sm font-normal">/{t.get("repos_total", 0)}</span></div><div class="text-xs text-gray-500 mt-0.5">Repos actifs</div></div>'
    html += f'<div class="bg-white rounded-xl border border-gray-200 px-4 py-3"><div class="text-2xl font-bold text-gray-900">{t.get("window", 0)}</div><div class="text-xs text-gray-500 mt-0.5">Builds / 7 jours</div></div>'
    html += f'<div class="bg-white rounded-xl border border-gray-200 px-4 py-3"><div class="text-2xl font-bold text-gray-900">{len(builds.get("deploys", []))}</div><div class="text-xs text-gray-500 mt-0.5">Déploiements récents</div></div>'
    html += '</div>'

    if not days:
        html += '<div class="bg-white rounded-xl border border-gray-200 px-6 py-5 text-sm text-gray-500">Aucun commit détecté sur les 7 derniers jours.</div>'
        return html

    # Timeline par jour
    for day in days:
        is_today = day.get("date") == today
        badge = '<span class="text-xs rounded px-1.5 py-0.5 bg-blue-50 text-blue-700 ml-2">aujourd’hui</span>' if is_today else ""
        html += '<div class="mb-6">'
        html += (
            '<div class="flex items-baseline gap-2 mb-2">'
            f'<h2 class="text-sm font-bold text-gray-700 uppercase tracking-wide">{escape(_fr_day(day.get("date", "")))}</h2>'
            f'{badge}'
            f'<span class="text-xs text-gray-400">{day.get("count", 0)} build(s)</span>'
            '</div>'
        )
        html += '<div class="bg-white rounded-xl border border-gray-200 overflow-hidden">'
        for repo in day.get("repos", []):
            html += (
                '<div class="px-4 py-3 border-b border-gray-100 last:border-0">'
                '<div class="flex items-center gap-2 mb-2">'
                f'<span class="text-sm font-semibold text-gray-900">{escape(repo.get("name", ""))}</span>'
                f'<span class="text-xs text-gray-400 font-mono">{escape(repo.get("repo", ""))}</span>'
                f'<span class="text-xs text-gray-400">· {len(repo.get("commits", []))} commit(s)</span>'
                '</div>'
            )
            for c in repo.get("commits", []):
                t_str = (c.get("date", "") or "")[11:16]
                html += (
                    '<div class="flex gap-3 items-start py-1 text-sm">'
                    f'<span class="text-xs font-mono text-gray-400 shrink-0 w-10 pt-0.5">{escape(t_str)}</span>'
                    f'<span class="text-xs font-mono bg-gray-100 rounded px-1.5 py-0.5 text-gray-600 shrink-0">{escape(c.get("hash", ""))}</span>'
                    f'<span class="text-gray-700 min-w-0 break-words">{escape(c.get("message", ""))} <span class="text-xs text-gray-400">· {escape(c.get("author", ""))}</span></span>'
                    '</div>'
                )
            html += '</div>'
        html += '</div></div>'

    deploys = builds.get("deploys", []) or []
    if deploys:
        html += '<div class="bg-white rounded-xl border border-gray-200 px-4 py-3 mb-6">'
        html += '<div class="text-sm font-bold text-gray-900 mb-2">Déploiements détectés (pages QG récentes)</div>'
        for d in deploys:
            html += (
                '<div class="flex gap-3 items-center py-1 text-xs border-t border-gray-50 first:border-0">'
                f'<span class="font-mono text-gray-400 shrink-0">{escape(d.get("mtime", ""))}</span>'
                f'<span class="font-mono text-gray-600">{escape(d.get("path", ""))}</span>'
                '</div>'
            )
        html += '</div>'

    return html


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    built_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    previous_ledgers = _read_existing_daily_ledgers()
    data = payload(built_at)
    ledger = daily_ledger(data, built_at)
    ledger_history = _merge_daily_ledgers(ledger, previous_ledgers)

    tmp = PUBLIC.parent / "public_build_tmp"
    if tmp.exists():
        import shutil
        shutil.rmtree(tmp)
    (tmp / "api").mkdir(parents=True)

    (tmp / "api" / "core-repos.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    # Republie les sorties des crons triage/vps-doctor (public/ est détruit à chaque build).
    # En worktree propre, ROOT/var est souvent absent: on conserve alors le snapshot public/api existant.
    for var_name in ("triage.json", "vps.json", "decisions.json"):
        var_payload = _read_var_json(var_name)
        if var_payload:
            (tmp / "api" / var_name).write_text(json.dumps(var_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    ledger_dir = tmp / "api" / "daily-ledger"
    ledger_dir.mkdir(parents=True, exist_ok=True)
    (ledger_dir / f"{ledger['date']}.json").write_text(
        json.dumps(ledger, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    for old_ledger in ledger_history[1:]:
        old_date = old_ledger.get("date")
        if old_date:
            (ledger_dir / f"{old_date}.json").write_text(
                json.dumps(old_ledger, ensure_ascii=False, indent=2), encoding="utf-8"
            )
    (ledger_dir / "index.json").write_text(
        json.dumps({"latest": f"/api/daily-ledger/{ledger['date']}.json", "items": ledger_history}, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    decisions = []
    try:
        decisions = json.loads((ROOT / "var" / "decisions.json").read_text(encoding="utf-8"))
    except Exception:
        pass

    # Builds du jour (commits par repo, 7 j) → public/api/builds.json
    try:
        builds = _load_build_ledger().collect_builds()
    except Exception as exc:  # ne casse jamais le build du QG
        builds = {"totals": {"today": 0, "window": 0, "repos_today": 0, "repos_total": 0}, "today": "", "days": [], "deploys": [], "error": str(exc)}
    (tmp / "api" / "builds.json").write_text(
        json.dumps(builds, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    pending_decisions = sum(1 for d in decisions if (d.get("statut") or "").lower() == "ouverte")
    builds_today = (builds.get("totals", {}) or {}).get("today", 0)

    pages = [
        ("/",             "registry",    "Registry CORE OA",        page_registry(data, pending_decisions, builds_today)),
        ("/ops/",         "ops",         "Ops quotidien",           page_ops(ledger)),
        ("/clients/",     "clients",     "Clients & VPS",           page_clients(data)),
        ("/decisions/",   "decisions",   "Décisions",                page_decisions(decisions)),
        ("/builds/",      "builds",      "Builds du jour",           page_builds(builds)),
        ("/partenaires/", "partenaires", "Partenaires",              page_partenaires(data)),
        ("/changelog/",   "changelog",   "Changelog",                page_changelog()),
    ]
    for app in data.get("items", []):
        pages.append((_app_route(app), "registry", f'{app.get("name", "App")} · fiche app', page_app_detail(data, app, builds, ledger_history)))
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
    print(f"built qg {len(pages)} routes · {healthy}/{data['counts']['total']} healthy · {issues} issues · {prs} PRs · ledger {ledger['date']} · {built_at}")


if __name__ == "__main__":
    main()
