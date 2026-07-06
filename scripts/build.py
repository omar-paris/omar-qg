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
    if spec is None or spec.loader is None:
        raise RuntimeError("build-ledger.py introuvable")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _load_repo_health():
    """Importe scripts/repo_health.py pour publier le snapshot QG."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "repo_health", Path(__file__).resolve().parent / "repo_health.py"
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("repo_health.py introuvable")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _load_agent_loop_registry():
    """Importe scripts/agent_loop_registry.py pour publier le registry P4."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "agent_loop_registry", Path(__file__).resolve().parent / "agent_loop_registry.py"
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("agent_loop_registry.py introuvable")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _load_storage_collector():
    """Importe scripts/collect_storage.py pour publier le snapshot stockage QG."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "collect_storage", Path(__file__).resolve().parent / "collect_storage.py"
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("collect_storage.py introuvable")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

def _load_blocages_collector():
    """Importe scripts/collect_blocages.py — vue « Ce qui bloque » (var/blocages.json)."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "collect_blocages", Path(__file__).resolve().parent / "collect_blocages.py"
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("collect_blocages.py introuvable")
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

# Les domaines OA internes utilisent Caddy `tls internal` sur le Tailnet :
# le build QG doit pouvoir les sonder même si l'autorité interne n'est pas
# installée dans le trust store système. Ce contexte CERT_NONE est strictement
# réservé aux health probes `*.omar.paris` et ne doit jamais transporter de
# secrets vers des API fournisseurs publiques.
_INTERNAL_OMAR_PARIS_SSL = ssl.create_default_context()
_INTERNAL_OMAR_PARIS_SSL.check_hostname = False
_INTERNAL_OMAR_PARIS_SSL.verify_mode = ssl.CERT_NONE

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

INTERNAL_HEALTH_PROBE_DOMAINS = frozenset(
    domain
    for item in ITEMS
    for domain in [item.get("domain", "").strip().lower().rstrip(".")]
    if domain.endswith(".omar.paris")
)


def _is_internal_health_probe_domain(domain: str) -> bool:
    return domain.strip().lower().rstrip(".") in INTERNAL_HEALTH_PROBE_DOMAINS

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
        # Schéma RBAC `access` (cf. rbac-model §4.2/4.3). VPS-Omar = CORE, aucune
        # vue client : pas de `client_view`, il n'apparaît dans aucune vue client.
        "access": {
            "owner": "alex",
            "viewers": ["ccma", "h-omar"],
            "exposure": "tailnet",
            "client_view": [],
            "internal_only": ["ip", "hetzner_id", "price_eur", "tailnet", "specs", "cost"],
        },
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
        "access": {
            "owner": "alex",
            "viewers": ["ccma", "h-aurel"],
            "exposure": "tailnet",
            "client_view": [],
            "internal_only": ["ip", "hetzner_id", "price_eur", "tailnet", "specs", "cost"],
        },
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
        # VPS client : jab est owner de SON vps. La vue client n'expose que
        # health/services/invoice ; jamais ip/hetzner_id/price_eur/tailnet/specs/cost.
        "access": {
            "owner": "jab",
            "viewers": ["alex", "ccma", "h-omar"],
            "exposure": "public-authenticated",
            "client_view": ["health", "services", "invoice"],
            "internal_only": ["ip", "hetzner_id", "price_eur", "tailnet", "specs", "cost"],
        },
        "links": [
            {"kind": "hub",       "label": "Hub local",       "url": "",                               "status": "todo"},
            {"kind": "hermesui",  "label": "Hermes UI",       "url": "",                               "status": "todo"},
            {"kind": "monitoring","label": "Glances",         "url": "",                               "status": "todo"},
            {"kind": "monitoring","label": "Console Hetzner", "url": "https://console.hetzner.cloud/", "status": "live"},
        ],
    },
}

# ── RBAC : isolation client (Standard 3) ──────────────────────────────────────
# Implémente le modèle de 11-Pilotage/night-agent/reports/2026-06-09-qg-rbac-model.md.
# Slice fondatrice : build NIVEAU 2 (§5) — artefacts statiques par rôle, filtrés au
# build, isolation client prouvable par test. Aucune logique d'autorisation runtime.

RBAC_DIR = ROOT / "rbac"

# Champs jamais exposés en vue client, quel que soit le `internal_only` déclaré
# par une ressource. Filet de sécurité défensif (defense-in-depth) : même si une
# ressource oublie de lister un de ces champs, il ne fuitera pas en vue client.
SENSITIVE_FIELDS = frozenset({
    "ip", "hetzner_id", "id", "price_eur", "tailnet",
    "datacenter", "location", "os", "type", "vcpu", "ram_gb", "disk_gb",
    "traffic_out_gb", "traffic_inc_tb", "created", "backups",
    "specs", "spec", "cost", "costs", "cost_eur", "coûts", "couts",
    "price", "monthly_cost", "server_name",
})


def _load_yaml(path: Path) -> dict:
    """Charge un YAML simple. Utilise PyYAML si présent, sinon parseur minimal
    (le build cron ne doit jamais casser faute de dépendance)."""
    try:
        import yaml  # type: ignore
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except ImportError:
        return _parse_actors_minimal(path)


def _parse_actors_minimal(path: Path) -> dict:
    """Parseur de secours pour rbac/actors.yaml uniquement (format inline maîtrisé)."""
    actors: dict = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].rstrip()
        if not line or not line.startswith("  ") or ":" not in line:
            continue
        key, _, rest = line.strip().partition(":")
        rest = rest.strip()
        if not (rest.startswith("{") and rest.endswith("}")):
            continue
        entry: dict = {}
        for pair in rest[1:-1].split(","):
            if ":" in pair:
                k, _, v = pair.partition(":")
                entry[k.strip()] = v.strip()
        actors[key.strip()] = entry
    return {"actors": actors}


def load_actors() -> dict:
    """Renvoie le dict {actor_id: {kind, role_default, scope?}} depuis actors.yaml."""
    data = _load_yaml(RBAC_DIR / "actors.yaml")
    return (data or {}).get("actors", {}) if isinstance(data, dict) else {}


def actor_can_see(actor: str, access: dict) -> bool:
    """Vrai si `actor` est owner ou viewer de la ressource décrite par `access`."""
    if not isinstance(access, dict):
        return False
    return actor == access.get("owner") or actor in (access.get("viewers") or [])


def client_fields(access: dict) -> list:
    """Champs autorisés en vue client = `client_view` moins tout champ sensible."""
    allowed = access.get("client_view") or [] if isinstance(access, dict) else []
    return [f for f in allowed if f not in SENSITIVE_FIELDS]


def filter_resource_for_client(resource: dict, access: dict) -> dict:
    """Projette une ressource sur sa vue client : ne garde QUE les champs
    `client_view` (hors champs sensibles) + des étiquettes non sensibles.

    Garantie : aucun champ de `internal_only` ni de SENSITIVE_FIELDS n'en sort.
    """
    fields = client_fields(access)
    public_label = resource.get("label") or resource.get("name")
    out = {
        # Étiquettes d'identification non sensibles (jamais une IP/coût/id infra)
        # Priorité au label statique métier : le nom live Hetzner peut contenir
        # des specs/naming infra (ex. ubuntu-4gb-*) et ne doit pas fuiter.
        "name": public_label,
        "label": public_label,
        "role": resource.get("role"),
        "fields": {},
    }
    for f in fields:
        if f in resource:
            out["fields"][f] = resource[f]
        elif f == "health":
            # santé dérivée des liens / d'un éventuel probe ; valeur neutre par défaut
            out["fields"]["health"] = resource.get("health", "unknown")
        elif f == "services":
            out["fields"]["services"] = resource.get("services", [])
        elif f == "invoice":
            out["fields"]["invoice"] = resource.get("invoice", {"status": "n/a"})
    return out


def build_client_view(client_id: str) -> dict:
    """Construit la vue client (Niveau 2) : UNIQUEMENT les ressources où
    `client_id` est owner/viewer, et UNIQUEMENT les champs `client_view`.

    Source = VPS_META (statique, toujours disponible même sans API Hetzner).
    Enrichi des champs live de la flotte Hetzner s'ils sont accessibles.
    """
    actors = load_actors()
    role = (actors.get(client_id) or {}).get("role_default", "client")

    # Enrichissement live optionnel (ne bloque jamais : worktree propre = pas de token)
    live_by_key: dict = {}
    try:
        for entry in hetzner_fleet():
            for key in VPS_META:
                if key in (entry.get("name") or ""):
                    live_by_key[key] = entry
                    break
    except Exception:
        live_by_key = {}

    resources = []
    for key, meta in VPS_META.items():
        access = meta.get("access") or {}
        if not actor_can_see(client_id, access):
            continue
        # Le rôle effectif sur CETTE ressource décide de la projection.
        # Un client ne voit que la vue client ; on n'expose la vue client que si
        # des champs client_view existent (sinon ressource interne, on l'omet).
        if role == "client" and not client_fields(access):
            continue
        base = dict(meta)
        base["name"] = meta.get("label", key)
        live = live_by_key.get(key)
        if isinstance(live, dict):
            base = {**base, **{k: v for k, v in live.items() if k not in ("access", "links")}}
        resources.append(filter_resource_for_client(base, access))

    return {
        "schema": "oa.rbac.client-view/1",
        "client": client_id,
        "role": role,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "resource_count": len(resources),
        "resources": resources,
    }


def client_view_html(view: dict) -> str:
    """Rendu HTML minimal de la vue client (portail app, derrière auth)."""
    rows = ""
    for r in view.get("resources", []):
        fields_html = "".join(
            f'<div class="text-sm text-gray-600"><span class="font-medium text-gray-800">{escape(str(k))}</span> : {escape(json.dumps(v, ensure_ascii=False))}</div>'
            for k, v in (r.get("fields") or {}).items()
        )
        rows += (
            '<div class="bg-white rounded-lg border border-gray-200 p-4 mb-3">'
            f'<div class="font-semibold text-gray-900">{escape(str(r.get("name") or r.get("label") or ""))}</div>'
            f'{fields_html}</div>'
        )
    if not rows:
        rows = '<div class="text-sm text-gray-500">Aucune ressource.</div>'
    return (
        '<!doctype html><html lang="fr"><head><meta charset="utf-8">'
        f'<title>Espace client {escape(str(view.get("client","")))}</title>'
        '<meta name="robots" content="noindex">'
        '<script src="https://cdn.tailwindcss.com"></script></head>'
        '<body class="bg-gray-50 p-6"><div class="max-w-2xl mx-auto">'
        f'<h1 class="text-xl font-bold text-gray-900 mb-1">Espace client · {escape(str(view.get("client","")))}</h1>'
        f'<p class="text-sm text-gray-500 mb-4">Vue client (santé, services, facture). '
        f'{view.get("resource_count",0)} ressource(s).</p>'
        f'{rows}</div></body></html>'
    )


def write_client_view(client_id: str, out_root: Path | None = None) -> Path:
    """Génère public/client/<id>/index.html + public/api/client-<id>.json.
    Renvoie le chemin du JSON (artefact testable)."""
    out_root = out_root or PUBLIC
    view = build_client_view(client_id)
    api_dir = out_root / "api"
    api_dir.mkdir(parents=True, exist_ok=True)
    json_path = api_dir / f"client-{client_id}.json"
    json_path.write_text(json.dumps(view, ensure_ascii=False, indent=2), encoding="utf-8")
    html_dir = out_root / "client" / client_id
    html_dir.mkdir(parents=True, exist_ok=True)
    (html_dir / "index.html").write_text(client_view_html(view), encoding="utf-8")
    return json_path


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
        internal_probe = _is_internal_health_probe_domain(domain)
        if _tok and internal_probe:
            _hdrs["X-OA-Token"] = _tok
        req = urllib.request.Request(url, headers=_hdrs)
        if internal_probe:
            response = urllib.request.urlopen(req, timeout=8, context=_INTERNAL_OMAR_PARIS_SSL)
        else:
            response = urllib.request.urlopen(req, timeout=8)
        with response as r:
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
        # API fournisseurs publiques : ne pas passer de contexte CERT_NONE.
        # Laisser urllib utiliser le contexte TLS par défaut vérifié, surtout
        # quand les headers portent des tokens Vault.
        with urllib.request.urlopen(req, timeout=timeout) as r:
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
            "access": meta.get("access", {}),
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
    ("/manifeste/",   "manifeste",   "Manifeste",   'M12 6.042A8.967 8.967 0 0 0 6 3.75c-1.052 0-2.062.18-3 .512v14.25A8.987 8.987 0 0 1 6 18c2.305 0 4.408.867 6 2.292m0-14.25a8.966 8.966 0 0 1 6-2.292c1.052 0 2.062.18 3 .512v14.25A8.987 8.987 0 0 0 18 18a8.967 8.967 0 0 0-6 2.292m0-14.25v14.25'),
    ("/",             "registry",    "Registry",    'M3.75 12h16.5m-16.5 3.75h16.5M3.75 19.5h16.5M5.625 4.5h12.75a1.875 1.875 0 0 1 0 3.75H5.625a1.875 1.875 0 0 1 0-3.75Z'),
    ("/blocages/",    "blocages",    "Blocages",    'M18.364 18.364A9 9 0 0 0 5.636 5.636m12.728 12.728A9 9 0 0 1 5.636 5.636m12.728 12.728L5.636 5.636'),
    ("/objectifs/",   "objectifs",   "Objectifs",   'M12 21a9.004 9.004 0 0 0 8.716-6.747M12 21a9.004 9.004 0 0 1-8.716-6.747M12 21c2.485 0 4.5-4.03 4.5-9S14.485 3 12 3m0 18c-2.485 0-4.5-4.03-4.5-9S9.515 3 12 3m0 0a8.997 8.997 0 0 1 7.843 4.582M12 3a8.997 8.997 0 0 0-7.843 4.582m15.686 0A11.953 11.953 0 0 1 12 10.5c-2.998 0-5.74-1.1-7.843-2.918m15.686 0A8.959 8.959 0 0 1 21 12c0 .778-.099 1.533-.284 2.253m0 0A17.919 17.919 0 0 1 12 16.5c-3.162 0-6.133-.815-8.716-2.247m0 0A9.015 9.015 0 0 1 3 12c0-1.605.42-3.113 1.157-4.418'),
    ("/chantiers/",   "chantiers",   "Chantiers",   'M11.42 15.17 17.25 21A2.652 2.652 0 0 0 21 17.25l-5.877-5.877M11.42 15.17l2.496-3.03c.317-.384.74-.626 1.208-.766M11.42 15.17l-4.655 5.653a2.548 2.548 0 1 1-3.586-3.586l6.837-5.63m5.108-.233c.55-.164 1.163-.188 1.743-.14a4.5 4.5 0 0 0 4.486-6.336l-3.276 3.277a3.004 3.004 0 0 1-2.25-2.25l3.276-3.276a4.5 4.5 0 0 0-6.336 4.486c.091 1.076-.071 2.264-.904 2.95l-.102.085m-1.745 1.437L5.909 7.5H4.5L2.25 3.75l1.5-1.5L7.5 4.5v1.409l4.26 4.26m-1.745 1.437 1.745-1.437m6.615 8.206L15.75 15.75M4.867 19.125h.008v.008h-.008v-.008Z'),
    ("/agent-loop/",  "agent-loop",  "Agent loop",  'M3.75 12a8.25 8.25 0 0 1 14.49-5.42M20.25 6.75v-4.5m0 4.5h-4.5M20.25 12a8.25 8.25 0 0 1-14.49 5.42M3.75 17.25v4.5m0-4.5h4.5'),
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

def _latest_delivered_result(builds: dict) -> dict:
    """mandat:h-omar-night-2026-06-14 — dernier commit livré visible QG."""
    for day in builds.get("days", []) or []:
        for repo in day.get("repos", []) or []:
            commits = repo.get("commits", []) or []
            if commits:
                commit = commits[0]
                return {
                    "repo": repo.get("repo") or repo.get("name") or "repo inconnu",
                    "hash": commit.get("hash") or "—",
                    "message": commit.get("message") or "Résultat non nommé",
                    "date": commit.get("date") or day.get("date") or "",
                }
    return {"repo": "—", "hash": "—", "message": "Aucun résultat livré détecté sur 7 jours", "date": ""}


def qg_delivery_focus(builds: dict, pending_decisions: int) -> str:
    """mandat:h-omar-night-2026-06-14 — bloc cockpit résultat/mandats."""
    latest = _latest_delivered_result(builds)
    when = (latest.get("date") or "")[:16].replace("T", " ")
    return (
        '<div class="grid grid-cols-1 lg:grid-cols-2 gap-3 mb-6">'
        '<a href="/builds/" class="block bg-white rounded-xl border border-blue-100 px-4 py-3 hover:border-blue-300 hover:shadow-sm transition">'
        '<div class="text-xs font-semibold uppercase tracking-wide text-blue-600">Dernier résultat livré</div>'
        f'<div class="mt-1 text-sm font-semibold text-gray-900">{escape(latest.get("message", ""))}</div>'
        f'<div class="mt-1 text-xs text-gray-500"><span class="font-mono">{escape(latest.get("repo", ""))}</span> · <span class="font-mono">{escape(latest.get("hash", ""))}</span>'
        + (f' · {escape(when)}' if when else '')
        + '</div><div class="mt-2 text-xs text-blue-500">Voir builds/preuves →</div></a>'
        '<a href="/decisions/" class="block bg-white rounded-xl border border-amber-100 px-4 py-3 hover:border-amber-300 hover:shadow-sm transition">'
        '<div class="text-xs font-semibold uppercase tracking-wide text-amber-600">Décisions / mandats</div>'
        f'<div class="mt-1 text-sm font-semibold text-gray-900">{pending_decisions} décision(s) ouverte(s)</div>'
        '<div class="mt-1 text-xs text-gray-500">Mandat actif: mandat:h-omar-night-2026-06-14 · décisions tracées en decision:*</div>'
        '<div class="mt-2 text-xs text-amber-600">Voir décisions →</div></a>'
        '</div>'
    )


def qg_blocages_banner(blocages: dict | None) -> str:
    """Bandeau d'entrée de la home (demande Alex 06/07) : compteur live → /blocages/.

    Même circulation que pending_decisions : le payload vient de collect_blocages.py
    (var/blocages.json) et le bandeau est rendu EN PREMIER sur la home.
    """
    compteurs = (blocages or {}).get("compteurs", {}) if isinstance(blocages, dict) else {}
    try:
        total = int(compteurs.get("total") or 0)
        pour_alex = int(compteurs.get("pour_alex") or 0)
        effort = int(compteurs.get("effort_min_alex") or 0)
    except Exception:
        total, pour_alex, effort = 0, 0, 0
    if total == 0:
        return (
            '<a href="/blocages/" class="block bg-green-50 rounded-xl border border-green-200 px-4 py-3 mb-6 hover:border-green-300 transition">'
            '<div class="text-xs font-semibold uppercase tracking-wide text-green-700">Blocages</div>'
            '<div class="mt-1 text-sm font-semibold text-green-700">Rien ne te bloque — le système avance seul.</div></a>'
        )
    accent = "amber" if pour_alex else "blue"
    detail = f"{total} blocage(s), dont {pour_alex} pour Alex"
    if effort:
        detail += f" (~{effort} min d'actions connues)"
    return (
        f'<a href="/blocages/" class="block bg-white rounded-xl border border-{accent}-200 px-4 py-3 mb-6 hover:border-{accent}-400 hover:shadow-sm transition">'
        f'<div class="flex items-center justify-between gap-3">'
        f'<div><div class="text-xs font-semibold uppercase tracking-wide text-{accent}-600">Ce qui bloque — et qui débloque</div>'
        f'<div class="mt-1 text-sm font-semibold text-gray-900">{escape(detail)}</div></div>'
        f'<span class="text-2xl font-bold text-{accent}-600">{total}</span></div>'
        f'<div class="mt-1 text-xs text-{accent}-600">Voir les blocages →</div></a>'
    )


def page_registry(data: dict, pending_decisions: int = 0, builds_today: int = 0, objectifs: list | None = None, builds: dict | None = None, agent_loop_audit: dict | None = None, blocages: dict | None = None) -> str:
    items = data["items"]
    counts = data["counts"]
    objectifs = objectifs or []
    builds = builds or {"days": []}
    audit_summary = (agent_loop_audit or {}).get("summary", {}) or {}
    total_orphans = int(audit_summary.get("total_orphans") or 0)

    # Tuiles d'action : décisions à trancher + builds du jour (liens dédiés)
    dec_accent = "text-amber-600" if pending_decisions else "text-gray-900"
    tiles = (
        '<div class="grid grid-cols-1 sm:grid-cols-3 gap-3 mb-3">'
        f'<a href="/decisions/" class="block bg-white rounded-xl border border-gray-200 px-4 py-3 hover:border-blue-300 hover:shadow-sm transition">'
        f'<div class="flex items-center justify-between"><div><div class="text-2xl font-bold {dec_accent}">{pending_decisions}</div>'
        f'<div class="text-xs text-gray-500 mt-0.5">Décisions en attente</div></div>'
        f'<span class="text-xs text-blue-500">Trancher →</span></div></a>'
        f'<a href="/builds/" class="block bg-white rounded-xl border border-gray-200 px-4 py-3 hover:border-blue-300 hover:shadow-sm transition">'
        f'<div class="flex items-center justify-between"><div><div class="text-2xl font-bold text-gray-900">{builds_today}</div>'
        f'<div class="text-xs text-gray-500 mt-0.5">Builds aujourd’hui</div></div>'
        f'<span class="text-xs text-blue-500">Voir →</span></div></a>'
        f'<a href="/agent-loop/" class="block bg-white rounded-xl border border-gray-200 px-4 py-3 hover:border-blue-300 hover:shadow-sm transition">'
        f'<div class="flex items-center justify-between"><div><div class="text-2xl font-bold {"text-red-600" if total_orphans else "text-gray-900"}">{total_orphans}</div>'
        f'<div class="text-xs text-gray-500 mt-0.5">Orphelins Issue↔Kanban↔PR↔Gate</div></div>'
        f'<span class="text-xs text-blue-500">Auditer →</span></div></a>'
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
    # EN PREMIER : le bandeau blocages (demande Alex 06/07), puis les objectifs, puis le registry.
    return qg_blocages_banner(blocages) + objectifs_summary(objectifs) + header + qg_delivery_focus(builds, pending_decisions) + tiles + stats + rows


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


def page_ops(ledger: dict, repo_health: dict | None = None, storage: dict | None = None) -> str:
    gh = ledger.get("github_totals", {})
    hermes = ledger.get("sessions", {}).get("hermes", {})
    cc = ledger.get("sessions", {}).get("ccusage", {})
    by_agent = cc.get("sessions_by_agent", {}) or {}
    cc_sessions = sum(_num(v.get("sessions")) for v in by_agent.values())
    cc_daily = cc.get("daily") or {}
    alerts = ledger.get("alerts", [])
    repo_health = repo_health or {}
    repo_totals = repo_health.get("totals", {}) if isinstance(repo_health, dict) else {}
    storage = storage or {}

    def card(label: str, value: object, sub: str = "") -> str:
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
    html += card("Repos dirty", repo_totals.get("dirty", sum(1 for r in ledger.get("repos", []) if (r.get("git") or {}).get("dirty"))), f"{repo_totals.get('p0', 0)} P0 · {repo_totals.get('p1', 0)} P1 · {repo_totals.get('p2', 0)} P2")
    html += card("Alertes", len(alerts) + len(repo_health.get("alerts", []) if isinstance(repo_health, dict) else []), "ledger + repo-health")
    html += '</div>'

    if isinstance(repo_health, dict) and repo_health.get("repos"):
        html += '<div class="bg-white rounded-xl border border-gray-200 overflow-hidden mb-6">'
        html += '<div class="px-4 py-3 border-b border-gray-100 flex items-center justify-between"><div><div class="text-sm font-bold text-gray-900">Repo Health — boucle QG obligatoire</div><div class="text-xs text-gray-400">Seuils explicites: PR en conflit=P0, drift massif >72h=P0, source dirty/âge >24h=P1</div></div><a href="/api/repo-health.json" class="text-xs text-blue-500 hover:underline">API repo-health</a></div>'
        html += '<div class="grid md:grid-cols-[80px_1fr_90px_90px_1fr] gap-2 px-4 py-2 bg-gray-50 text-xs font-semibold text-gray-500 uppercase hidden md:grid"><span>Risque</span><span>Repo</span><span>Dirty</span><span>PRs</span><span>Prochaine action</span></div>'
        for rr in repo_health.get("repos", [])[:8]:
            risk = str(rr.get("risk", "OK"))
            cls = "pill-err" if risk == "P0" else "pill-warn" if risk in {"P1", "P2"} else "pill-ok"
            prs = rr.get("open_prs") or []
            html += (
                '<div class="grid md:grid-cols-[80px_1fr_90px_90px_1fr] gap-2 px-4 py-3 border-b border-gray-100 last:border-0 text-sm items-start">'
                f'<div><span class="{cls} inline-flex rounded-full px-2 py-0.5 text-xs font-medium">{escape(risk)}</span></div>'
                f'<div><div class="font-semibold text-gray-900">{escape(str(rr.get("name") or rr.get("slug") or ""))}</div><div class="text-xs text-gray-400 font-mono">{escape(str(rr.get("branch") or ""))}</div></div>'
                f'<div class="text-gray-700">{escape(str(rr.get("dirty_count", 0)))}<div class="text-xs text-gray-400">{escape(str(rr.get("oldest_dirty_age_hours") or "—"))}h</div></div>'
                f'<div class="text-gray-700">{len(prs)}</div>'
                f'<div class="text-gray-600 text-xs leading-relaxed">{escape(str(rr.get("next_action") or ""))}</div>'
                '</div>'
            )
        html += '</div>'

    if isinstance(storage, dict) and storage:
        st_status = str(storage.get("status", "unknown"))
        st_cls = {"ok": "border-green-200 bg-green-50 text-green-800", "warning": "border-yellow-200 bg-yellow-50 text-yellow-800", "critical": "border-red-200 bg-red-50 text-red-800"}.get(st_status, "border-gray-200 bg-gray-50 text-gray-700")
        html += '<section class="bg-white rounded-xl border border-gray-200 overflow-hidden mb-6">'
        html += '<div class="px-4 py-3 border-b border-gray-100 flex items-center justify-between gap-3">'
        html += '<div><h2 class="text-sm font-bold text-gray-900">Stockage &amp; sauvegardes</h2><p class="text-xs text-gray-500">Read-only · VPS root, volumes, backups Hermes DB, rclone.</p></div>'
        html += f'<span class="inline-flex rounded-full border px-2.5 py-1 text-xs font-semibold {st_cls}">{escape(st_status.upper())}</span>'
        html += '</div>'
        html += '<div class="grid md:grid-cols-3 gap-3 px-4 py-3">'
        for m in storage.get("mounts", [])[:3]:
            s = str(m.get("status", "unknown"))
            pct = m.get("used_pct")
            cls = "text-green-700" if s == "ok" else ("text-red-700" if s == "critical" else "text-amber-700")
            html += '<div class="rounded-lg border border-gray-100 px-3 py-2">'
            html += f'<div class="flex items-center justify-between"><div class="text-xs font-semibold text-gray-900">{escape(str(m.get("label") or m.get("path") or ""))}</div><div class="text-xs font-bold {cls}">{escape(str(pct)) if pct is not None else "—"}%</div></div>'
            html += f'<div class="text-xs text-gray-400 font-mono mt-1">{escape(str(m.get("path", "")))}</div>'
            html += f'<div class="text-xs text-gray-500 mt-1">libre {escape(str(m.get("free_h", "—")))} · cible {escape(str(m.get("target_pct", "—")))}%</div>'
            html += '</div>'
        html += '</div>'
        mem = storage.get("memory", {}) or {}
        swap = mem.get("swap", {}) or {}
        backups = storage.get("backup_sets", []) or []
        b0 = backups[0] if backups else {}
        remotes = ((storage.get("cloud_archives", {}) or {}).get("rclone", {}) or {}).get("remotes", []) or []
        docker = storage.get("docker", {}) or {}
        safe_prune = "oui" if docker.get("safe_to_prune") else "non"
        docker_sub = f"hint brut {docker.get('theoretical_reclaimable_hint') or '—'} · dangling {docker.get('dangling_images', '—')} · stopped {docker.get('containers_stopped', '—')}"
        html += '<div class="grid md:grid-cols-4 gap-3 px-4 pb-3">'
        html += f'<div class="rounded-lg bg-gray-50 px-3 py-2"><div class="text-xs text-gray-500">Swap</div><div class="text-lg font-bold text-gray-900">{escape(str(swap.get("used_pct", "—")))}%</div><div class="text-xs text-gray-400">{escape(str(swap.get("used_h", "—")))} / {escape(str(swap.get("total_h", "—")))}</div></div>'
        html += f'<div class="rounded-lg bg-gray-50 px-3 py-2"><div class="text-xs text-gray-500">Backups Hermes DB</div><div class="text-lg font-bold text-gray-900">{escape(str(b0.get("count", "—")))} archives</div><div class="text-xs text-gray-400">{escape(str(b0.get("total_h", "—")))} · {escape(str(b0.get("retention_policy", "—")))}</div></div>'
        html += f'<div class="rounded-lg bg-gray-50 px-3 py-2"><div class="text-xs text-gray-500">Docker prune sûr</div><div class="text-lg font-bold text-gray-900">{escape(safe_prune)}</div><div class="text-xs text-gray-400">{escape(docker_sub)}</div></div>'
        html += f'<div class="rounded-lg bg-gray-50 px-3 py-2"><div class="text-xs text-gray-500">Archives cloud</div><div class="text-lg font-bold text-gray-900">{escape(str(len(remotes)))} remotes</div><div class="text-xs text-gray-400">{escape(", ".join(map(str, remotes)) or "non mesuré")}</div></div>'
        html += '</div>'
        risks = storage.get("risks", []) or []
        actions = storage.get("recommended_actions", []) or []
        if risks or actions:
            html += '<div class="grid md:grid-cols-2 gap-3 px-4 pb-4">'
            html += '<div><div class="text-xs font-semibold uppercase tracking-wide text-gray-400 mb-1">Risques</div>'
            if risks:
                for r in risks[:5]:
                    html += f'<div class="text-xs text-gray-600 py-1 border-t border-gray-50"><span class="font-semibold">{escape(str(r.get("code", "RISK")))}</span> — {escape(str(r.get("message", "")))}</div>'
            else:
                html += '<div class="text-xs text-green-700">Aucun risque stockage critique.</div>'
            html += '</div><div><div class="text-xs font-semibold uppercase tracking-wide text-gray-400 mb-1">Actions recommandées</div>'
            if actions:
                for a in actions[:5]:
                    html += f'<div class="text-xs text-gray-600 py-1 border-t border-gray-50">{escape(str(a))}</div>'
            else:
                html += '<div class="text-xs text-green-700">Pas d’action immédiate.</div>'
            html += '</div></div>'
        html += '<div class="px-4 py-2 border-t border-gray-100"><a href="/api/ops/storage-summary.json" class="text-xs text-blue-500 hover:underline">API storage-summary</a></div>'
        html += '</section>'

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


# ── Objectifs ───────────────────────────────────────────────────────────────

_OBJ_STATUTS = {
    "a_faire":  ("À faire",   "bg-gray-100 text-gray-600",   "bg-gray-300"),
    "en_cours": ("En cours",  "bg-blue-50 text-blue-700",    "bg-blue-500"),
    "fait":     ("Fait",      "bg-green-50 text-green-700",   "bg-green-500"),
}


def _obj_progress(obj: dict) -> int:
    try:
        p = int(obj.get("progression", 0) or 0)
    except (TypeError, ValueError):
        p = 0
    return max(0, min(100, p))


def _decision_label(did: str, by_id: dict) -> str:
    d = by_id.get(did)
    if not d:
        return did
    txt = str(d.get("texte", did))
    return txt if len(txt) <= 70 else txt[:67] + "…"


def page_objectifs(objectifs: list, decisions: list) -> str:
    """Couche OBJECTIFS du QG (qg) : ce qu'Alex vise, relié à ses décisions."""
    by_id = {d.get("id"): d for d in decisions if isinstance(d, dict) and d.get("id")}
    html = (
        '<div class="flex items-center justify-between mb-6">'
        '<div><h1 class="text-xl font-bold text-gray-900">Objectifs</h1>'
        f'<p class="text-sm text-gray-500 mt-0.5">{len(objectifs)} objectif(s) — ce qu\'Alex vise, relié aux décisions qui les débloquent.</p></div></div>'
    )
    if not objectifs:
        html += '<div class="bg-white border border-gray-200 rounded-xl px-5 py-4 text-sm text-gray-500">Aucun objectif défini.</div>'
        return html
    for obj in objectifs:
        statut = str(obj.get("statut", "a_faire"))
        label, badge_cls, bar_cls = _OBJ_STATUTS.get(statut, _OBJ_STATUTS["a_faire"])
        prog = _obj_progress(obj)
        html += '<div class="bg-white rounded-xl border border-gray-200 px-5 py-4 mb-3">'
        html += (
            '<div class="flex items-start justify-between gap-3 mb-2">'
            f'<div class="text-sm font-semibold text-gray-900">{escape(str(obj.get("titre", obj.get("id", "?"))))}</div>'
            f'<span class="shrink-0 text-xs rounded-full px-2 py-0.5 font-medium {badge_cls}">{escape(label)}</span>'
            '</div>'
        )
        if obj.get("description"):
            html += f'<div class="text-xs text-gray-500 mb-3">{escape(str(obj["description"]))}</div>'
        html += (
            '<div class="flex items-center gap-3 mb-3">'
            '<div class="flex-1 h-2 rounded-full bg-gray-100 overflow-hidden">'
            f'<div class="h-2 rounded-full {bar_cls}" style="width:{prog}%"></div></div>'
            f'<span class="text-xs font-medium text-gray-600 w-10 text-right">{prog}%</span>'
            '</div>'
        )
        liees = [d for d in (obj.get("decisions_liees") or []) if d]
        if liees:
            html += '<div class="flex flex-wrap gap-1.5 pt-1 border-t border-gray-100 mt-1">'
            html += '<span class="text-xs text-gray-400 mr-1 mt-0.5">Décisions liées :</span>'
            for did in liees:
                html += (
                    f'<a href="/decisions/#card-{escape(str(did))}" '
                    'class="text-xs rounded-full bg-amber-50 text-amber-700 px-2 py-0.5 hover:bg-amber-100" '
                    f'title="{escape(_decision_label(str(did), by_id))}">{escape(_decision_label(str(did), by_id))}</a>'
                )
            html += '</div>'
        html += '</div>'
    return html


def objectifs_summary(objectifs: list) -> str:
    """Bandeau Objectifs en tête de l'accueil (avant le registry de repos)."""
    if not objectifs:
        return ""
    cards = ""
    for obj in objectifs:
        statut = str(obj.get("statut", "a_faire"))
        label, badge_cls, bar_cls = _OBJ_STATUTS.get(statut, _OBJ_STATUTS["a_faire"])
        prog = _obj_progress(obj)
        cards += (
            '<a href="/objectifs/" class="block bg-white rounded-xl border border-gray-200 px-4 py-3 hover:border-blue-300 hover:shadow-sm transition">'
            '<div class="flex items-start justify-between gap-2 mb-2">'
            f'<div class="text-sm font-semibold text-gray-900 leading-snug">{escape(str(obj.get("titre", obj.get("id", "?"))))}</div>'
            f'<span class="shrink-0 text-xs rounded-full px-2 py-0.5 font-medium {badge_cls}">{escape(label)}</span>'
            '</div>'
            '<div class="flex items-center gap-2">'
            '<div class="flex-1 h-1.5 rounded-full bg-gray-100 overflow-hidden">'
            f'<div class="h-1.5 rounded-full {bar_cls}" style="width:{prog}%"></div></div>'
            f'<span class="text-xs font-medium text-gray-500 w-9 text-right">{prog}%</span>'
            '</div></a>'
        )
    return (
        '<div class="mb-6">'
        '<div class="flex items-center justify-between mb-2">'
        '<h2 class="text-sm font-semibold text-gray-700 uppercase tracking-wide">Objectifs</h2>'
        '<a href="/objectifs/" class="text-xs text-blue-500 hover:underline">Tout voir →</a>'
        '</div>'
        f'<div class="grid grid-cols-1 sm:grid-cols-2 gap-3">{cards}</div>'
        '</div>'
    )


def page_manifeste(manifeste: dict) -> str:
    """Page 1 du QG — le manifeste rendu (handbook-first, Fable 4D System Rescue).

    Source de vérité = docs 02/02bis/INDEX du dossier « Renew OA V2 - validated
    by Claude » (28/05/2026). Cette page les REND, elle ne les réécrit pas :
    var/manifeste.json (republié en /api/manifeste.json) est un extrait fidèle,
    toute évolution de fond passe par le doc 02 d'abord.
    """
    if not manifeste:
        return ('<h1 class="text-xl font-bold text-gray-900 mb-4">Manifeste</h1>'
                '<div class="bg-amber-50 border border-amber-200 rounded-xl px-5 py-4 text-sm text-amber-700">'
                'var/manifeste.json absent ou vide — le manifeste source reste '
                '<span class="font-mono">11-Pilotage/Renew OA V2 - validated by Claude/02-manifeste-business-interne.md</span>.</div>')

    offre = manifeste.get("offre") or {}
    footer = manifeste.get("footer") or {}

    # ── En-tête : promesse + règle handbook-first + fichiers sources ──────────
    sources_html = "".join(
        '<div class="flex items-baseline gap-2 text-xs py-0.5">'
        f'<span class="text-gray-500 shrink-0">{escape(str(s.get("label") or ""))}</span>'
        f'<span class="font-mono text-gray-400 break-all">{escape(str(s.get("path") or ""))}</span></div>'
        for s in manifeste.get("sources", [])
    )
    html = (
        '<div class="mb-6">'
        '<h1 class="text-xl font-bold text-gray-900">Manifeste — la boussole OA</h1>'
        '<p class="text-sm text-gray-500 mt-0.5">Page 1 du QG : l\'offre validée le 28/05/2026, rendue depuis les docs 02 / 02bis '
        '— source <a href="/api/manifeste.json" class="text-blue-500 hover:underline">manifeste.json</a>.</p>'
        '</div>'
        '<div class="bg-white rounded-xl border border-blue-200 px-6 py-5 mb-6">'
        '<div class="text-xs font-semibold uppercase tracking-wide text-blue-600 mb-2">La promesse client</div>'
        f'<div class="text-lg font-semibold text-gray-900 leading-snug">« {escape(str(manifeste.get("promesse") or ""))} »</div>'
        f'<div class="mt-3 text-sm text-gray-600 border-l-2 border-blue-200 pl-3">{escape(str(manifeste.get("regle") or ""))} '
        'Toute décision d\'offre est écrite dans le manifeste avant d\'être appliquée.</div>'
        f'<div class="mt-3 pt-3 border-t border-gray-100">{sources_html}</div>'
        '</div>'
    )

    # ── Funnel en 4 étapes ─────────────────────────────────────────────────────
    html += (
        '<div class="flex items-baseline gap-2 mb-3"><h2 class="text-sm font-bold uppercase tracking-wide text-gray-700">Le funnel</h2>'
        '<span class="text-xs text-gray-400">4 étapes, chacune portée par une brique — rang de finition dans '
        '<a href="/chantiers/" class="text-blue-500 hover:underline">/chantiers/</a></span></div>'
        '<div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-3 mb-6">'
    )
    for step in manifeste.get("funnel", []):
        nom = escape(str(step.get("nom") or ""))
        lien = str(step.get("lien") or "")
        horizon = str(step.get("chantier_horizon") or "")
        horizon_pill = "pill-ok" if horizon == "Now" else "pill-warn"
        brique = (f'<a href="{escape(lien)}" target="_blank" rel="noopener" class="text-xs text-blue-500 hover:underline break-all">{escape(lien.replace("https://", ""))}</a>'
                  if lien else '<span class="text-xs text-gray-400">brique à livrer — pas encore live</span>')
        html += (
            '<div class="bg-white rounded-xl border border-gray-200 px-4 py-4 flex flex-col">'
            '<div class="flex items-center justify-between mb-2">'
            f'<span class="w-6 h-6 rounded-full bg-blue-600 text-white text-xs font-bold flex items-center justify-center">{step.get("etape", "?")}</span>'
            f'<span class="px-2 py-0.5 rounded text-xs font-medium {horizon_pill}">{escape(horizon)} · rang {step.get("chantier_rang", "?")}</span></div>'
            f'<div class="text-sm font-semibold text-gray-900 mb-1">{nom}</div>'
            f'<div class="text-xs text-gray-600 mb-2 flex-1">{escape(str(step.get("role") or ""))}</div>'
            f'{brique}</div>'
        )
    html += '</div>'

    # ── L'offre : pour qui, quoi, différenciation ──────────────────────────────
    pour_qui = "".join(
        f'<div class="flex gap-2 text-sm text-gray-600 py-0.5"><span class="text-gray-300 shrink-0">—</span><span>{escape(str(p))}</span></div>'
        for p in offre.get("pour_qui", [])
    )
    services = "".join(
        '<div class="rounded-lg border border-gray-100 bg-gray-50 px-3 py-2">'
        f'<div class="text-xs font-semibold text-gray-800">{escape(str(s.get("nom") or ""))}</div>'
        f'<div class="text-xs text-gray-500 mt-0.5">{escape(str(s.get("raison") or ""))}</div></div>'
        for s in offre.get("services_avant", [])
    )
    diff = "".join(
        f'<div class="flex gap-2 text-sm text-gray-600 py-0.5"><span class="text-gray-300 shrink-0">—</span><span>{escape(str(d))}</span></div>'
        for d in offre.get("differenciation", [])
    )
    html += (
        '<h2 class="text-sm font-bold uppercase tracking-wide text-gray-700 mb-3">L\'offre <span class="font-normal normal-case text-xs text-gray-400">(résumé fidèle du doc 02)</span></h2>'
        '<div class="grid grid-cols-1 lg:grid-cols-3 gap-3 mb-3">'
        '<div class="bg-white rounded-xl border border-gray-200 px-5 py-4">'
        '<div class="text-xs font-semibold uppercase tracking-wide text-gray-500 mb-2">Pour qui</div>'
        f'{pour_qui}'
        f'<div class="text-xs text-gray-500 mt-2">{escape(str(offre.get("profil") or ""))}</div>'
        f'<div class="text-xs text-gray-400 mt-2"><span class="font-medium">Hors-cible :</span> {escape(str(offre.get("hors_cible") or ""))}</div></div>'
        '<div class="bg-white rounded-xl border border-gray-200 px-5 py-4">'
        '<div class="text-xs font-semibold uppercase tracking-wide text-gray-500 mb-2">Ce qu\'on livre</div>'
        f'<div class="text-sm text-gray-600 mb-3">{escape(str(offre.get("quoi") or ""))}</div>'
        f'<div class="space-y-2">{services}</div></div>'
        '<div class="bg-white rounded-xl border border-gray-200 px-5 py-4">'
        '<div class="text-xs font-semibold uppercase tracking-wide text-gray-500 mb-2">Différenciation</div>'
        f'{diff}</div>'
        '</div>'
        '<div class="bg-amber-50 border border-amber-200 rounded-xl px-5 py-3 mb-6 text-sm text-amber-800">'
        f'<span class="font-semibold">Pricing :</span> {escape(str(offre.get("pricing_note") or ""))} '
        '<a href="/decisions/" class="font-medium text-amber-700 underline hover:no-underline">Voir la décision →</a></div>'
    )

    # ── Les 4 socles ───────────────────────────────────────────────────────────
    html += (
        '<div class="flex items-baseline gap-2 mb-3"><h2 class="text-sm font-bold uppercase tracking-wide text-gray-700">Les 4 socles</h2>'
        '<span class="text-xs text-gray-400">l\'infrastructure qui porte le funnel</span></div>'
        '<div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-3 mb-6">'
    )
    for socle in manifeste.get("socles", []):
        lien = str(socle.get("lien") or "")
        html += (
            '<div class="bg-white rounded-xl border border-gray-200 px-4 py-4">'
            f'<div class="text-sm font-semibold text-gray-900 mb-1">{escape(str(socle.get("nom") or ""))}'
            f'<span class="ml-2 text-xs font-normal text-gray-400">rang {socle.get("chantier_rang", "?")}</span></div>'
            f'<div class="text-xs text-gray-600 mb-2">{escape(str(socle.get("role") or ""))}</div>'
            f'<a href="{escape(lien)}" target="_blank" rel="noopener" class="text-xs text-blue-500 hover:underline break-all">{escape(lien.replace("https://", "").rstrip("/"))}</a></div>'
        )
    html += '</div>'

    # ── Footer doctrine ────────────────────────────────────────────────────────
    html += (
        '<div class="border-t border-gray-200 pt-4 text-xs text-gray-500">'
        f'<div>{escape(str(footer.get("validation") or ""))}</div>'
        f'<div class="mt-1"><span class="font-medium text-gray-600">Règle handbook-first :</span> {escape(str(footer.get("handbook_first") or ""))}</div>'
        '</div>'
    )
    return html


def page_chantiers(chantiers: list) -> str:
    """Tableau Now/Next/Later des 8 briques (PRODUCT-TRUTH, Fable 4D System Rescue).

    Source statique : var/chantiers.json (republié en /api/chantiers.json). Chaque
    brique = carte avec rang de finition, objectif, écart vs promesse, effort et
    renvoi /decisions/ quand une décision Alex ouverte la bloque.
    """
    horizons = [
        ("now",   "Now",   "text-blue-700",  "à finir en premier — débloque le client réel"),
        ("next",  "Next",  "text-gray-700",  "juste après — funnel et outillage"),
        ("later", "Later", "text-gray-500",  "cohérence interne — aucun client n'attend dessus"),
    ]
    effort_cls = {"S": "pill-ok", "M": "pill-warn"}
    html = (
        '<div class="mb-6">'
        '<h1 class="text-xl font-bold text-gray-900">Chantiers — quoi finir, dans l\'ordre</h1>'
        '<p class="text-sm text-gray-500 mt-0.5">8 briques classées par le test doctrine « livrable client réel cette semaine ? » '
        '— source <a href="/api/chantiers.json" class="text-blue-500 hover:underline">chantiers.json</a> (PRODUCT-TRUTH 04/07).</p>'
        '</div>'
    )
    if not chantiers:
        return html + '<div class="bg-amber-50 border border-amber-200 rounded-xl px-5 py-4 text-sm text-amber-700">Aucun chantier chargé — var/chantiers.json absent ou vide.</div>'
    for key, label, title_cls, hint in horizons:
        briques = sorted([c for c in chantiers if c.get("horizon") == key], key=lambda c: c.get("rang", 99))
        if not briques:
            continue
        html += (
            f'<div class="flex items-baseline gap-2 mt-6 mb-3"><h2 class="text-sm font-bold uppercase tracking-wide {title_cls}">{escape(label)}</h2>'
            f'<span class="text-xs text-gray-400">{escape(hint)}</span></div>'
            '<div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">'
        )
        for c in briques:
            effort = str(c.get("effort") or "?")
            pill = effort_cls.get(effort, "pill-warn")
            nom = escape(str(c.get("nom") or "Brique"))
            titre = (f'<a href="{escape(c["lien"])}" target="_blank" rel="noopener" class="hover:underline">{nom}</a>'
                     if c.get("lien") else nom)
            html += (
                '<div class="bg-white rounded-xl border border-gray-200 px-5 py-4 flex flex-col">'
                '<div class="flex items-center justify-between mb-2">'
                '<div class="flex items-center gap-2">'
                f'<span class="w-6 h-6 rounded-full bg-gray-900 text-white text-xs font-bold flex items-center justify-center">{c.get("rang", "?")}</span>'
                f'<span class="text-sm font-semibold text-gray-900">{titre}</span></div>'
                f'<span class="px-2 py-0.5 rounded text-xs font-medium {pill}">effort {escape(effort)}</span></div>'
                f'<div class="text-sm text-gray-700 mb-2">{escape(str(c.get("objectif") or ""))}</div>'
                f'<div class="text-xs text-gray-500 mb-2"><span class="font-medium text-gray-600">Écart :</span> {escape(str(c.get("ecart") or ""))}</div>'
            )
            if c.get("preuve"):
                html += f'<div class="text-xs text-gray-400 mb-2"><span class="font-medium">Preuve :</span> <span class="font-mono">{escape(str(c["preuve"]))}</span></div>'
            html += '<div class="mt-auto pt-2 flex items-center justify-between gap-2">'
            html += f'<span class="text-xs text-gray-400">{escape(str(c.get("owner") or ""))}</span>'
            if c.get("decision_attendue"):
                html += '<a href="/decisions/" class="text-xs font-medium text-amber-600 hover:underline">décision en attente →</a>'
            html += '</div></div>'
        html += '</div>'
    return html


def page_blocages(payload: dict) -> str:
    """« Ce qui bloque — et qui débloque » — vue unique dédupliquée (demande Alex 06/07).

    Source : var/blocages.json (collect_blocages.py, republié en /api/blocages.json).
    Groupé par qui_debloque (Alex d'abord), trié par âge décroissant.
    """
    payload = payload if isinstance(payload, dict) else {}
    blocages = payload.get("blocages") if isinstance(payload.get("blocages"), list) else []
    compteurs = payload.get("compteurs", {}) if isinstance(payload.get("compteurs"), dict) else {}
    generated_at = str(payload.get("generated_at") or "non renseigné")
    try:
        total = int(compteurs.get("total") or 0)
        pour_alex = int(compteurs.get("pour_alex") or 0)
        effort = int(compteurs.get("effort_min_alex") or 0)
    except Exception:
        total, pour_alex, effort = len(blocages), 0, 0

    type_badges = {
        "decision": ("décision", "pill-warn"),
        "carte":    ("carte",    "bg-blue-50 text-blue-700 border border-blue-200"),
        "sudo":     ("sudo",     "pill-err"),
        "pr":       ("PR",       "bg-purple-50 text-purple-700 border border-purple-200"),
    }
    groupes = [
        ("alex",    "Alex — à toi de jouer",       "text-amber-700"),
        ("h-omar",  "H-Omar — arbitrage & infra",  "text-blue-700"),
        ("agent",   "Agents — rework en cours",    "text-gray-700"),
        ("externe", "Externe — hors de nos mains", "text-gray-500"),
    ]
    resume = f"{total} blocage(s), dont {pour_alex} pour Alex"
    if effort:
        resume += f" — ~{effort} min d'actions Alex connues"
    html = (
        '<div class="mb-6">'
        '<h1 class="text-xl font-bold text-gray-900">Ce qui bloque — et qui débloque</h1>'
        f'<p class="text-sm text-gray-500 mt-0.5">{escape(resume)} · décisions, cartes Kanban, sudo et PRs dédupliqués — '
        f'source <a href="/api/blocages.json" class="text-blue-500 hover:underline">blocages.json</a> ({escape(generated_at)}).</p>'
        '</div>'
    )
    if not blocages:
        return html + (
            '<div class="bg-green-50 border border-green-200 rounded-xl px-5 py-4 text-sm text-green-700">'
            'Rien ne te bloque — le système avance seul.</div>'
        )
    for qui, label, title_cls in groupes:
        items = sorted(
            [b for b in blocages if isinstance(b, dict) and b.get("qui_debloque") == qui],
            key=lambda b: -(b.get("age_jours") or 0),
        )
        if not items:
            continue
        html += (
            f'<div class="flex items-baseline gap-2 mt-6 mb-2"><h2 class="text-sm font-bold uppercase tracking-wide {title_cls}">{escape(label)}</h2>'
            f'<span class="text-xs text-gray-400">{len(items)} blocage(s)</span></div>'
            '<div class="bg-white rounded-xl border border-gray-200 divide-y divide-gray-100">'
        )
        for b in items:
            btype = str(b.get("type") or "carte")
            badge_label, badge_cls = type_badges.get(btype, (btype, "pill-warn"))
            titre = escape(str(b.get("titre") or "Blocage sans titre"))
            lien = str(b.get("lien") or "")
            if lien:
                target = ' target="_blank" rel="noopener"' if lien.startswith("http") else ""
                titre = f'<a href="{escape(lien)}"{target} class="hover:text-blue-600 hover:underline">{titre}</a>'
            age = int(b.get("age_jours") or 0)
            age_cls = "text-red-600 font-semibold" if age >= 7 else ("text-amber-600" if age >= 3 else "text-gray-400")
            effort_min = b.get("effort_min")
            html += (
                '<div class="px-4 py-3">'
                '<div class="flex items-center gap-2 flex-wrap">'
                f'<span class="inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium {badge_cls}">{escape(badge_label)}</span>'
                f'<span class="text-sm font-medium text-gray-900">{titre}</span>'
                f'<span class="text-xs {age_cls}">{age} j</span>'
                + (f'<span class="pill-ok inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium">{int(effort_min)} min</span>' if effort_min else '')
                + '</div>'
                f'<div class="text-xs text-gray-500 mt-1">{escape(str(b.get("action_1_ligne") or ""))}</div>'
                '</div>'
            )
        html += '</div>'
    errors = payload.get("errors") if isinstance(payload.get("errors"), list) else []
    if errors:
        html += (
            '<div class="mt-6 text-xs text-gray-400">Sources partielles : '
            + escape(" · ".join(str(e) for e in errors[:6]))
            + '</div>'
        )
    return html


def page_decisions(decisions: list) -> str:
    """Boîte de décisions Alex (qg#27) — réponse = bouton → qg-api → déblocage kanban/issue."""
    # URL relative: passe par le vhost qg.omar.paris (proxy Caddy /api/decisions* -> 8097).
    # L'ancienne URL http:// en dur etait bloquee en mixed-content depuis la page https.
    api = "/api/decisions/answer"
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


def page_agent_loop_audit(report: dict, registry: dict | None = None) -> str:
    """Surface QG read-only des orphelins Issue↔Kanban↔PR↔Gate + registry des boucles prouvées."""
    registry = registry or {}
    registry_summary = registry.get("summary", {}) if isinstance(registry, dict) else {}
    registry_items = registry.get("items", []) if isinstance(registry, dict) else []
    summary = report.get("summary", {}) if isinstance(report, dict) else {}
    total = int(summary.get("total_orphans") or 0)
    checked_at = report.get("checked_at") or "non généré"

    def card(label: str, key: str, tone: str = "text-gray-900") -> str:
        value = int(summary.get(key) or 0)
        return (
            '<div class="bg-white rounded-xl border border-gray-200 px-4 py-3">'
            f'<div class="text-2xl font-bold {tone if value else "text-gray-900"}">{value}</div>'
            f'<div class="text-xs text-gray-500 mt-0.5">{escape(label)}</div></div>'
        )

    def row(section: str, item: dict) -> str:
        title = item.get("title") or item.get("url") or item.get("card_id") or "orphelin"
        target = item.get("url") or ""
        ident = item.get("expected_key") or item.get("card_id") or "—"
        action = item.get("action") or "inspect"
        if target:
            left = f'<a href="{escape(target)}" class="text-sm font-semibold text-gray-900 hover:text-blue-600 hover:underline">{escape(str(title))}</a>'
        else:
            left = f'<div class="text-sm font-semibold text-gray-900">{escape(str(title))}</div>'
        return (
            '<div class="grid md:grid-cols-[170px_1fr_240px_190px] gap-2 px-4 py-3 border-b border-gray-100 last:border-0">'
            f'<div class="text-xs font-semibold text-gray-500 uppercase tracking-wide">{escape(section)}</div>'
            f'<div>{left}</div>'
            f'<div class="text-xs font-mono text-gray-500 break-all">{escape(str(ident))}</div>'
            f'<div class="text-xs text-amber-700">{escape(str(action))}</div>'
            '</div>'
        )

    rows = ""
    sections = [
        ("Issue agent-ok sans carte", "issues_without_card"),
        ("PR ouverte sans gate", "prs_without_gate"),
        ("Builder review-required sans Athena", "builder_cards_without_gate"),
        ("Blocked sans owner/next_action", "blocked_without_next_action"),
        ("Scheduled périmé", "stale_scheduled"),
    ]
    for label, key in sections:
        for item in report.get(key, []) if isinstance(report, dict) else []:
            if isinstance(item, dict):
                rows += row(label, item)
    if not rows:
        rows = '<div class="px-4 py-5 text-sm text-green-700 bg-green-50">Aucun orphelin détecté dans le dernier audit.</div>'

    errors = (report.get("errors") or []) if isinstance(report, dict) else []
    errors_html = ""
    if errors:
        errors_html = '<div class="mt-4 bg-amber-50 border border-amber-200 rounded-xl px-4 py-3"><div class="text-sm font-semibold text-amber-800">Collecte dégradée</div>'
        errors_html += "".join(f'<div class="text-xs text-amber-700 font-mono mt-1">{escape(str(e))}</div>' for e in errors[:5])
        errors_html += '</div>'

    registry_cards = ""
    for key, label in [("prs", "PR"), ("cards", "Cartes"), ("gates", "Gates"), ("merges", "Merges"), ("artifacts", "Artefacts")]:
        registry_cards += (
            '<div class="bg-white rounded-xl border border-gray-200 px-4 py-3">'
            f'<div class="text-2xl font-bold text-gray-900">{escape(str(registry_summary.get(key, 0)))}</div>'
            f'<div class="text-xs text-gray-500 mt-0.5">{escape(label)} prouvés</div></div>'
        )
    registry_rows = ""
    for item in registry_items[:12] if isinstance(registry_items, list) else []:
        if not isinstance(item, dict):
            continue
        kind = str(item.get("kind") or "objet")
        title = item.get("title") or item.get("url") or item.get("path") or item.get("number") or kind
        status = item.get("status") or item.get("state") or "—"
        ref = item.get("id") or item.get("url") or item.get("path") or "—"
        registry_rows += (
            '<div class="grid md:grid-cols-[90px_1fr_120px_1fr] gap-2 px-4 py-3 border-b border-gray-100 last:border-0 text-sm">'
            f'<div class="text-xs font-semibold uppercase tracking-wide text-gray-500">{escape(kind)}</div>'
            f'<div class="font-semibold text-gray-900">{escape(str(title))}</div>'
            f'<div class="text-xs text-gray-600">{escape(str(status))}</div>'
            f'<div class="text-xs font-mono text-gray-500 break-all">{escape(str(ref))}</div>'
            '</div>'
        )
    if not registry_rows:
        registry_rows = '<div class="px-4 py-5 text-sm text-gray-500">Aucune boucle prouvée publiée dans le registry.</div>'

    return (
        '<div class="flex items-center justify-between mb-6"><div>'
        '<h1 class="text-xl font-bold text-gray-900">Audit anti-orphelins</h1>'
        f'<p class="text-sm text-gray-500 mt-0.5">Issue ↔ Kanban ↔ PR ↔ Gate — dernier scan {escape(str(checked_at))}.</p></div>'
        '<div class="flex gap-3"><a href="/api/agent-loop-registry.json" class="text-xs text-blue-500 hover:underline">API registry</a><a href="/api/agent-loop-audit.json" class="text-xs text-blue-500 hover:underline">API audit</a></div></div>'
        '<div class="grid grid-cols-2 lg:grid-cols-6 gap-3 mb-6">'
        f'<div class="bg-white rounded-xl border border-gray-200 px-4 py-3"><div class="text-2xl font-bold {"text-red-600" if total else "text-gray-900"}">{total}</div><div class="text-xs text-gray-500 mt-0.5">Total orphelins</div></div>'
        + card("Issues agent-ok sans carte", "issues_without_card", "text-red-600")
        + card("PRs sans gate", "prs_without_gate", "text-red-600")
        + card("Review-required sans Athena", "builder_cards_without_gate", "text-red-600")
        + card("Blocked sans action", "blocked_without_next_action", "text-amber-600")
        + card("Scheduled périmés", "stale_scheduled", "text-amber-600")
        + '</div><div class="bg-white rounded-xl border border-gray-200 overflow-hidden mb-6">'
        '<div class="px-4 py-3 border-b border-gray-100"><div class="text-sm font-bold text-gray-900">Boucles prouvées — registry P4</div><div class="text-xs text-gray-400">Source: artefacts H-Omar/Builder/Athena déjà vérifiés.</div></div>'
        '<div class="grid grid-cols-2 lg:grid-cols-5 gap-3 p-4 bg-gray-50">' + registry_cards + '</div>'
        + registry_rows + '</div><div class="bg-white rounded-xl border border-gray-200 overflow-hidden">'
        '<div class="px-4 py-3 border-b border-gray-100"><div class="text-sm font-bold text-gray-900">Orphelins et actions à prendre</div></div>'
        + rows + '</div>' + errors_html
    )


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

def _parse_args(argv: list[str]) -> dict:
    """Parse les options CLI minimales : --view=<operator|client> --client=<id>."""
    opts = {"view": "operator", "client": None}
    for arg in argv:
        if arg.startswith("--view="):
            opts["view"] = arg.split("=", 1)[1]
        elif arg.startswith("--client="):
            opts["client"] = arg.split("=", 1)[1]
        elif arg == "--view":
            continue
    return opts


def main(argv: list[str] | None = None) -> None:
    import sys
    opts = _parse_args(list(argv) if argv is not None else sys.argv[1:])

    # NIVEAU 2 (rbac-model §5) : build d'une vue client isolée. Artefact statique
    # ne contenant QUE les ressources du client + champs client_view. Le build
    # operator/normal reste inchangé et rétrocompatible (branche ci-dessous).
    if opts["view"] == "client":
        client_id = opts.get("client")
        if not client_id:
            raise SystemExit("usage: build.py --view=client --client=<id>")
        json_path = write_client_view(client_id)
        view = json.loads(json_path.read_text(encoding="utf-8"))
        print(
            f"built client view '{client_id}' · {view['resource_count']} resource(s) · "
            f"{json_path.relative_to(PUBLIC.parent)} + public/client/{client_id}/index.html"
        )
        return

    built_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    previous_ledgers = _read_existing_daily_ledgers()
    # Blocages (« Ce qui bloque — et qui débloque ») : collecte AU DÉBUT du build,
    # best-effort — le cron n'appelle que build.py, jamais le collecteur seul.
    try:
        blocages_payload = _load_blocages_collector().collect(write=True)
    except Exception as exc:  # ne casse jamais le build QG
        blocages_payload = _read_var_json("blocages.json")
        if not isinstance(blocages_payload, dict) or not blocages_payload:
            blocages_payload = {
                "schema": "oa.blocages/1",
                "generated_at": built_at,
                "compteurs": {"total": 0, "pour_alex": 0, "effort_min_alex": 0, "par_type": {}, "par_qui": {}},
                "blocages": [],
                "errors": [f"blocages_unavailable: {exc.__class__.__name__}"],
            }


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
    for var_name in ("triage.json", "vps.json", "decisions.json", "objectifs.json", "chantiers.json", "manifeste.json", "builder-pr-autogate.json"):
        var_payload = _read_var_json(var_name)
        if var_payload:
            (tmp / "api" / var_name).write_text(json.dumps(var_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    # Blocages : snapshot collecté en tête de build → /api/blocages.json.
    (tmp / "api" / "blocages.json").write_text(
        json.dumps(blocages_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
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
    if not decisions:
        # Worktree propre : pas de var/, on retombe sur le snapshot publié.
        snap = _read_var_json("decisions.json")
        decisions = snap if isinstance(snap, list) else []

    # Couche OBJECTIFS (qg) : ce qu'Alex vise. var/ runtime, fallback public/api en worktree propre.
    objectifs = _read_var_json("objectifs.json")
    if not isinstance(objectifs, list):
        objectifs = []

    # Couche CHANTIERS (Fable 4D rescue) : ordre de finition Now/Next/Later des 8 briques.
    chantiers = _read_var_json("chantiers.json")
    if not isinstance(chantiers, list):
        chantiers = []

    # Couche MANIFESTE (Fable 4D rescue, handbook-first) : extrait fidèle des docs
    # 02/02bis validés 28/05 — la page d'entrée conceptuelle du QG.
    manifeste = _read_var_json("manifeste.json")
    if not isinstance(manifeste, dict):
        manifeste = {}

    # Audit anti-orphelins Issue↔Kanban↔PR↔Gate : produit par scripts/agent_loop_audit.py.
    # Le build reste read-only et republie le dernier snapshot disponible.
    agent_loop_audit = _read_var_json("agent-loop-audit.json")
    if not isinstance(agent_loop_audit, dict) or not agent_loop_audit:
        agent_loop_audit = {
            "schema": "oa.agent-loop-audit/1",
            "status": "unknown",
            "checked_at": None,
            "summary": {
                "total_orphans": 0,
                "issues_without_card": 0,
                "prs_without_gate": 0,
                "builder_cards_without_gate": 0,
                "blocked_without_next_action": 0,
                "stale_scheduled": 0,
            },
            "issues_without_card": [],
            "prs_without_gate": [],
            "builder_cards_without_gate": [],
            "blocked_without_next_action": [],
            "stale_scheduled": [],
            "errors": ["agent-loop-audit snapshot absent — run scripts/agent_loop_audit.py"],
        }
    (tmp / "api" / "agent-loop-audit.json").write_text(
        json.dumps(agent_loop_audit, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    try:
        agent_loop_registry = _load_agent_loop_registry().collect()
    except Exception as exc:  # ne casse jamais le build QG
        agent_loop_registry = {
            "schema": "oa.agent-loop-registry/1",
            "status": "degraded",
            "generated_at": built_at,
            "source": "scripts/agent_loop_registry.py",
            "summary": {"issues": 0, "cards": 0, "prs": 0, "gates": 0, "merges": 0, "artifacts": 0},
            "items": [],
            "errors": [f"agent-loop-registry unavailable: {exc.__class__.__name__}"],
        }
    (tmp / "api" / "agent-loop-registry.json").write_text(
        json.dumps(agent_loop_registry, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # Repo Health v0 — snapshot canonique pour éviter la redécouverte manuelle.
    try:
        repo_health = _load_repo_health().collect()
    except Exception as exc:  # ne casse jamais le build QG
        repo_health = {
            "schema": "oa.repo-health/1",
            "generated_at": built_at,
            "source": "scripts/repo_health.py",
            "totals": {"repos": 0, "dirty": 0, "p0": 0, "p1": 0, "p2": 0, "ok": 0, "open_prs": 0, "conflict_prs": 0},
            "alerts": [{"level": "P1", "code": "REPO_HEALTH_UNAVAILABLE", "message": f"Collecte repo-health indisponible: {exc.__class__.__name__}"}],
            "repos": [],
        }
    (tmp / "api" / "repo-health.json").write_text(
        json.dumps(repo_health, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # Stockage & sauvegardes — read-only pour /ops/ et API QG.
    try:
        storage = _load_storage_collector().collect()
    except Exception as exc:  # ne casse jamais le build QG
        storage = {
            "meta": {"schema_version": "0.1", "mode": "dynamic-readonly", "source": "scripts/collect_storage.py"},
            "status": "unknown",
            "mounts": [],
            "memory": {},
            "backup_sets": [],
            "cloud_archives": {},
            "risks": [{"level": "warning", "code": "STORAGE_UNAVAILABLE", "message": f"Collecte stockage indisponible: {exc.__class__.__name__}"}],
            "recommended_actions": [],
        }
    (tmp / "api" / "ops").mkdir(parents=True, exist_ok=True)
    (tmp / "api" / "ops" / "storage-summary.json").write_text(
        json.dumps(storage, ensure_ascii=False, indent=2), encoding="utf-8"
    )

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
        ("/manifeste/",   "manifeste",   "Manifeste",               page_manifeste(manifeste)),
        ("/",             "registry",    "Registry CORE OA",        page_registry(data, pending_decisions, builds_today, objectifs, builds, agent_loop_audit, blocages_payload)),
        ("/blocages/",    "blocages",    "Blocages",                page_blocages(blocages_payload)),
        ("/objectifs/",   "objectifs",   "Objectifs",               page_objectifs(objectifs, decisions)),
        ("/chantiers/",   "chantiers",   "Chantiers",               page_chantiers(chantiers)),
        ("/agent-loop/",  "agent-loop",  "Audit anti-orphelins",     page_agent_loop_audit(agent_loop_audit, agent_loop_registry)),
        ("/ops/",         "ops",         "Ops quotidien",           page_ops(ledger, repo_health, storage)),
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
