#!/usr/bin/env python3
from __future__ import annotations

import datetime as dt
import json
import os
import re
import ssl
import stat
import sqlite3
import subprocess
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from contextlib import contextmanager
from dataclasses import dataclass
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


def _load_agent_activity():
    """Importe scripts/agent_activity.py pour publier la vue dynamique agents."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "agent_activity", Path(__file__).resolve().parent / "agent_activity.py"
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("agent_activity.py introuvable")
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


def _load_carte_collector():
    """Importe scripts/collect_carte.py — la Carte du puzzle (var/carte.json)."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "collect_carte", Path(__file__).resolve().parent / "collect_carte.py"
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("collect_carte.py introuvable")
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

def _load_graded_for_node(node_id: str, qg_root: Path):
    """Conformité graduée 4 couleurs d'un node.
    - Omar : depuis son ledger local oa-compliance-run (omar-top).
    - VPS distant (jab/pantheos) : depuis l'artefact EXPÉDIÉ (ship-own) déposé en
      var/graded-conformity-<id>.json — le QG ne lit JAMAIS le VPS en direct."""
    if node_id in ("oa-master", "omar", "vps-omar"):
        comp = Path("/home/omar/23-Offre/actifs/omar-top/state/compliance/omar")
        runs = comp / "runs.jsonl"
        if not runs.exists():
            return None
        run_lines = [l for l in runs.read_text().splitlines() if l.strip()]
        if not run_lines:
            return None
        last = json.loads(run_lines[-1])
        laws: dict = {}
        vpath = comp / "verdicts.jsonl"
        if vpath.exists():
            for line in vpath.read_text().splitlines():
                if not line.strip():
                    continue
                v = json.loads(line)
                if v.get("run_id") == last.get("run_id"):
                    laws[v["law_id"]] = v.get("couleur")
        return {
            "schema": "oa.graded-conformity/v1", "grade": last.get("vps_grade"),
            "tally": last.get("tally"), "run_id": last.get("run_id"), "laws": laws,
            "source": "oa-compliance-run (omar-top ledger, local)",
        }
    # Cherché là où atterrissent les artefacts expédiés (var QG + inbox du pull inter-VPS).
    candidates = [
        qg_root / "var" / f"graded-conformity-{node_id}.json",
        Path(f"/home/omar/11-Pilotage/sujets-actifs/inter-vps-inbox/{node_id}-pull/graded-conformity.json"),
    ]
    for shipped in candidates:
        if shipped.exists():
            try:
                g = json.loads(shipped.read_text())
                g.setdefault("source", "ship-own (expédié par le VPS)")
                return g
            except Exception:
                continue
    return None


def _inject_graded_conformity(fleet_supervision_v0: dict) -> None:
    """Fleet-ready : injecte la conformité graduée dans CHAQUE node qui en a une.
    Omar depuis son ledger ; jab/pantheos dès qu'ils poussent leur artefact gradué."""
    qg_root = Path(__file__).resolve().parents[1]
    for node in fleet_supervision_v0.get("nodes", []):
        nid = node.get("node") or node.get("id")
        try:
            g = _load_graded_for_node(nid, qg_root)
        except Exception:
            g = None
        if g:
            node["conformite_graduee"] = g


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

HETZNER_VAULT_PATH = "secret/integrations/hetzner/test"

PROVIDERS = {
    "hetzner":     {"name": "Hetzner",     "logo": "H", "color": "#d50c2d", "url": "https://www.hetzner.com",       "vault_key": HETZNER_VAULT_PATH},
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
            {"kind": "hermesui",  "label": "Hermes UI",      "url": "https://hermes.omar.paris/",         "status": "live"},
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


@dataclass(frozen=True)
class VaultReadResult:
    """Secret read outcome without including Vault output or secret values."""

    status: str
    data: dict


def _vault_read(path: str) -> VaultReadResult:
    """Read a Vault KV secret while preserving safe operational failure classes."""
    try:
        completed = subprocess.run(
            ["/usr/bin/vault", "kv", "get", "-format=json", path],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=_vault_env(),
            check=False,
        )
    except OSError:
        return VaultReadResult(status="vault_unavailable", data={})

    if completed.returncode:
        error_text = (completed.stderr or "").lower()
        if "no value found" in error_text or "not found" in error_text:
            return VaultReadResult(status="secret_missing", data={})
        if "no space left on device" in error_text or "audit" in error_text:
            return VaultReadResult(status="vault_unavailable", data={})
        return VaultReadResult(status="api_error", data={})

    try:
        data = json.loads(completed.stdout).get("data", {}).get("data", {})
    except (TypeError, ValueError, AttributeError):
        return VaultReadResult(status="api_error", data={})
    if not isinstance(data, dict):
        return VaultReadResult(status="api_error", data={})
    return VaultReadResult(status="ok", data=data)


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
    vault = _vault_read("secret/integrations/ovh")
    if vault.status != "ok":
        return "key_missing" if vault.status == "secret_missing" else vault.status
    creds = vault.data
    if not creds.get("OVH_CONSUMER_KEY"):
        return "key_missing"
    return "ok" if _ovh_get("/me", creds) else "error"


def probe_telnyx() -> str:
    vault = _vault_read("secret/integrations/telnyx")
    if vault.status != "ok":
        return "key_missing" if vault.status == "secret_missing" else vault.status
    creds = vault.data
    key = creds.get("TELNYX_API_KEY", "")
    if not key:
        return "key_missing"
    code = _http_status("https://api.telnyx.com/v2/balance", {"Authorization": f"Bearer {key}"})
    return "ok" if code == 200 else "error"


def probe_hetzner() -> str:
    vault = _vault_read(HETZNER_VAULT_PATH)
    if vault.status != "ok":
        return "key_missing" if vault.status == "secret_missing" else vault.status
    creds = vault.data
    key = creds.get("HETZNER_API_TOKEN") or creds.get("HETZNER_TOKEN") or creds.get("HCLOUD_TOKEN", "")
    if not key:
        return "key_missing"
    code = _http_status("https://api.hetzner.cloud/v1/servers?per_page=1", {"Authorization": f"Bearer {key}"})
    return "ok" if code == 200 else "error"


def probe_infomaniak() -> str:
    vault = _vault_read("secret/integrations/infomaniak")
    if vault.status != "ok":
        return "key_missing" if vault.status == "secret_missing" else vault.status
    creds = vault.data
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


def hetzner_fleet_result() -> dict:
    """Return fleet items plus a safe status instead of silently masking Vault/API errors."""
    vault = _vault_read(HETZNER_VAULT_PATH)
    if vault.status != "ok":
        return {"items": [], "status": vault.status}
    creds = vault.data
    key = creds.get("HCLOUD_TOKEN") or creds.get("HETZNER_API_TOKEN") or creds.get("HETZNER_TOKEN", "")
    if not key:
        return {"items": [], "status": "secret_missing"}
    req = urllib.request.Request(
        "https://api.hetzner.cloud/v1/servers",
        headers={"Authorization": f"Bearer {key}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=8) as r:
            data = json.loads(r.read())
    except Exception:
        return {"items": [], "status": "api_error"}

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
    return {"items": fleet, "status": "ok"}


def hetzner_fleet() -> list:
    """Compatibility wrapper for callers that only need the live fleet entries."""
    return hetzner_fleet_result()["items"]


def _read_var_json(name: str) -> dict:
    """Read QG generated inputs without collecting new data.

    Runtime crons normally write ROOT/var/*.json. In clean worktrees those files are
    absent, so build-time pages fall back to the already-published public/api
    snapshots committed in the repo. This keeps app pages factual while respecting
    the issue #26 boundary: no extra API calls or fresh collection for detail pages.
    """
    paths = []
    if os.environ.get("QG_USE_TEST_FIXTURES") == "1":
        paths.append(ROOT / "tests" / "fixtures" / "qg-var" / name)
    paths.extend([ROOT / "var" / name, PUBLIC / "api" / name])
    for path in paths:
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


INTER_VPS_REPORT_DIRS = [
    Path("/home/omar/11-Pilotage/sujets-actifs/inter-vps-inbox"),
    # Legacy pre-canonical drop zone kept read-only until H-Aurel migrates its outbox.
    Path("/home/omar/11-Pilotage/sujets-actifs/fable-5-rails-1-2/inbox-from-pantheos"),
]
if os.environ.get("QG_USE_TEST_FIXTURES") == "1":
    # Fixtures EXCLUSIVES : sinon un rapport réel plus frais que la fixture rend
    # les tests non déterministes selon la machine (CI portable = fixtures only).
    INTER_VPS_REPORT_DIRS = [ROOT / "tests" / "fixtures" / "inter-vps-inbox"]

REQUIRED_VPS_APPS = [
    {"app_id": "hermes", "name": "Hermes local"},
    {"app_id": "omarhub", "name": "OmarHub local"},
    {"app_id": "tailscale", "name": "Tailscale"},
    {"app_id": "reverse-proxy", "name": "Caddy/nginx"},
    {"app_id": "inter-vps-reporter", "name": "Inter-VPS reporter"},
]

_VALID_APP_STATUSES = {"ok", "outdated", "missing", "unknown", "blocked"}


def _node_from_report(payload: dict, path: Path) -> str:
    node = str(payload.get("node") or "").strip().lower()
    if not node:
        vps_id = str(payload.get("vps_id") or "").strip().lower()
        if vps_id.startswith("vps-"):
            node = vps_id.removeprefix("vps-")
        elif vps_id:
            node = vps_id
    if not node and path.name == "vps-report-latest.json" and path.parent.name:
        node = path.parent.name.strip().lower()
    if not node:
        node = path.stem.split("-", 1)[0].strip().lower()
    return node


def _inter_vps_report_paths(root: Path) -> list[Path]:
    paths = set(root.rglob("*health*.json"))
    paths.update(root.rglob("vps-report-latest.json"))
    paths.update(root.rglob("*vps-report*.json"))
    return sorted(paths)


def _normalize_inter_vps_report_timestamps(payload: dict, path: Path) -> dict:
    """Conserve séparément heartbeat source et refresh local QG.

    Certains normaliseurs locaux réécrivent `generated_at` avec NOW tout en
    gardant le heartbeat natif dans `source_report_generated_at`. Le QG doit
    publier/mesurer la fraîcheur sur le timestamp source, et garder l'horloge
    locale uniquement dans `observed_at` / `normalized_at`.
    """
    normalized = dict(payload)
    local_generated_at = str(normalized.get("generated_at") or "unknown")
    source_generated_at = str(normalized.get("source_report_generated_at") or local_generated_at)
    normalized["source_report_generated_at"] = source_generated_at
    if normalized.get("source_report_generated_at") and source_generated_at != local_generated_at:
        normalized.setdefault("observed_at", local_generated_at)
        normalized.setdefault("normalized_at", local_generated_at)
        normalized["generated_at"] = source_generated_at
    else:
        normalized.setdefault("observed_at", str(normalized.get("observed_at") or "unknown"))
        normalized.setdefault("normalized_at", str(normalized.get("normalized_at") or "unknown"))
    normalized["_source_path"] = str(path)
    return normalized


def _read_inter_vps_reports() -> list[dict]:
    reports: dict[str, dict] = {}
    for root in INTER_VPS_REPORT_DIRS:
        if not root.exists():
            continue
        for path in _inter_vps_report_paths(root):
            if any(part in {"_invalid", "_validated"} for part in path.parts):
                continue
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if not isinstance(payload, dict) or payload.get("schema") != "oa.vps-report/v1":
                continue
            node = _node_from_report(payload, path)
            if not node:
                continue
            payload = _normalize_inter_vps_report_timestamps(payload, path)
            payload["node"] = node
            prev = reports.get(node)
            if not prev or str(payload.get("generated_at") or "") >= str(prev.get("generated_at") or ""):
                reports[node] = payload
    return [reports[k] for k in sorted(reports)]


def _infer_app_status_from_services(report: dict, app_id: str) -> tuple[str, str]:
    services = report.get("services") or []
    if not isinstance(services, list):
        services = []
    names = " ".join(str(s.get("name", "")) for s in services if isinstance(s, dict)).lower()
    statuses = [str(s.get("status", "")).lower() for s in services if isinstance(s, dict)]
    if app_id == "hermes" and "hermes" in names:
        return ("ok" if any("active" in st or "up" in st for st in statuses) else "unknown", "services")
    if app_id == "reverse-proxy" and ("caddy" in names or "nginx" in names):
        return ("ok" if any("active" in st or "up" in st for st in statuses) else "unknown", "services")
    security = report.get("security") or {}
    resources = report.get("resources") or {}
    sys_services = ((resources.get("system") or {}).get("services") if isinstance(resources, dict) else None) or {}
    if app_id == "tailscale" and (
        security.get("tailscale_first") is True
        or str(sys_services.get("tailscaled", "")).lower() == "active"
    ):
        return "ok", "report"
    return "unknown", "report"


def _app_verdict_from_status(status: str) -> str:
    normalized = str(status or "unknown").strip().lower()
    if normalized in {"pass", "ok", "running", "active", "healthy", "up", "installed"}:
        return "PASS"
    if normalized in {"fail", "failed", "stopped", "inactive", "missing", "blocked", "down", "error", "critical", "outdated"}:
        return "FAIL"
    return "UNKNOWN"


def _legacy_status_from_verdict(verdict: str, raw_status: str) -> str:
    if verdict == "PASS":
        return "ok"
    if verdict == "FAIL":
        raw = str(raw_status or "").strip().lower()
        if raw in {"missing", "outdated", "blocked"}:
            return raw
        return "blocked"
    return "unknown"


def _normalize_installed_app(raw: dict, report: dict) -> dict:
    app_id = str(raw.get("app_id") or raw.get("id") or raw.get("name") or "unknown").strip().lower()
    raw_status = str(raw.get("status") or raw.get("verdict") or "unknown").strip().lower()
    verdict = _app_verdict_from_status(str(raw.get("verdict") or raw_status))
    status = raw_status if raw_status in _VALID_APP_STATUSES else _legacy_status_from_verdict(verdict, raw_status)
    evidence = str(raw.get("evidence") or raw.get("proof_redacted") or "redacted report")
    return {
        "app_id": app_id,
        "name": str(raw.get("name") or app_id),
        "installed": bool(raw.get("installed", verdict == "PASS")),
        "version_installed": str(raw.get("version_installed") or raw.get("version") or "unknown"),
        "version_expected": str(raw.get("version_expected") or raw.get("version_min_required") or "policy-current"),
        "status": status,
        "verdict": verdict,
        "raw_status": raw_status,
        "source": str(raw.get("source") or raw.get("kind") or "report"),
        "evidence": evidence,
        "last_checked_at": str(raw.get("last_checked_at") or report.get("generated_at") or "unknown"),
    }


def _apps_for_report(report: dict) -> list[dict]:
    provided = []
    for key in ("installed_apps", "apps"):
        values = report.get(key) or []
        if isinstance(values, list):
            provided.extend(values)
    apps: dict[str, dict] = {}
    for raw in provided:
        if isinstance(raw, dict):
            app = _normalize_installed_app(raw, report)
            apps[app["app_id"]] = app
    for req in REQUIRED_VPS_APPS:
        app_id = req["app_id"]
        if app_id in apps:
            continue
        status, source = _infer_app_status_from_services(report, app_id)
        verdict = _app_verdict_from_status(status)
        apps[app_id] = {
            "app_id": app_id,
            "name": req["name"],
            "installed": verdict == "PASS",
            "version_installed": "unknown",
            "version_expected": "policy-current",
            "status": status,
            "verdict": verdict,
            "raw_status": status,
            "source": source,
            "evidence": "inferred from oa.vps-report/v1 (redacted)",
            "last_checked_at": str(report.get("generated_at") or "unknown"),
        }
    return [apps[k] for k in sorted(apps)]


def _normalize_standard(raw: dict, report: dict) -> dict:
    verdict = str(raw.get("verdict") or raw.get("status") or "UNKNOWN").strip().upper()
    if verdict not in {"PASS", "FAIL", "UNKNOWN"}:
        verdict = "UNKNOWN"
    return {
        "item_id": str(raw.get("item_id") or raw.get("id") or raw.get("control_id") or "unknown"),
        "label": str(raw.get("label") or raw.get("name") or raw.get("item_id") or raw.get("id") or "Standard OA"),
        "verdict": verdict,
        "evidence": str(raw.get("evidence") or raw.get("proof_redacted") or "redacted report"),
        "last_checked_at": str(raw.get("last_checked_at") or report.get("generated_at") or "unknown"),
    }


def _standards_for_report(report: dict) -> list[dict]:
    standards = report.get("standards") or []
    if not isinstance(standards, list):
        return []
    normalized = [_normalize_standard(raw, report) for raw in standards if isinstance(raw, dict)]
    return sorted(normalized, key=lambda x: x["item_id"])


APP_INVENTORY_ALIAS_NODES = {"oa-master": "omar"}


def _inventory_node_alias(node: str) -> dict:
    canonical = APP_INVENTORY_ALIAS_NODES.get(node, node)
    if canonical != node:
        return {
            "canonical_node": canonical,
            "alias_of": canonical,
            "alias_note": f"{node} est un flux santé local du même VPS que {canonical}; non compté comme VPS de supervision séparé.",
        }
    return {"canonical_node": canonical}


def collect_vps_app_inventory(built_at: str) -> dict:
    nodes = []
    for report in _read_inter_vps_reports():
        apps = _apps_for_report(report)
        standards = _standards_for_report(report)
        statuses = [a["status"] for a in apps]
        app_verdicts = [a["verdict"] for a in apps]
        standard_verdicts = [s["verdict"] for s in standards]
        node_name = str(report.get("node") or "unknown").lower()
        nodes.append({
            "node": node_name,
            **_inventory_node_alias(node_name),
            "vps_id": str(report.get("vps_id") or report.get("node") or "unknown"),
            "tenant": str(report.get("tenant") or report.get("scope") or "unknown"),
            "agent": str(report.get("agent") or "unknown"),
            "support": str(report.get("support") or ""),
            "health_status": str((report.get("health") or {}).get("status") or report.get("status") or report.get("maturity") or "unknown").lower(),
            "generated_at": str(report.get("generated_at") or "unknown"),
            "source_path": str(report.get("_source_path") or ""),
            "apps": apps,
            "standards": standards,
            "summary": {
                "total": len(apps),
                "ok": statuses.count("ok"),
                "outdated": statuses.count("outdated"),
                "missing": statuses.count("missing"),
                "unknown": statuses.count("unknown"),
                "blocked": statuses.count("blocked"),
                "pass": app_verdicts.count("PASS"),
                "fail": app_verdicts.count("FAIL"),
                "verdict_unknown": app_verdicts.count("UNKNOWN"),
            },
            "standards_summary": {
                "total": len(standards),
                "pass": standard_verdicts.count("PASS"),
                "fail": standard_verdicts.count("FAIL"),
                "unknown": standard_verdicts.count("UNKNOWN"),
            },
        })
    aliases = {
        alias: {
            "alias_of": canonical,
            "note": f"{alias} est affiché comme compatibilité inventaire; /ops/ traite {canonical} comme le VPS canonique.",
        }
        for alias, canonical in sorted(APP_INVENTORY_ALIAS_NODES.items())
        if any(n.get("node") == alias for n in nodes)
    }
    totals = {
        "nodes": len(nodes),
        "canonical_nodes": len({n.get("canonical_node") or n.get("node") for n in nodes}),
        "alias_nodes": len([n for n in nodes if n.get("alias_of")]),
        "apps": sum(n["summary"]["total"] for n in nodes),
    }
    for st in _VALID_APP_STATUSES:
        totals[st] = sum(n["summary"].get(st, 0) for n in nodes)
    for verdict_key in ("pass", "fail", "verdict_unknown"):
        totals[verdict_key] = sum(n["summary"].get(verdict_key, 0) for n in nodes)
    totals["standards"] = sum(n["standards_summary"].get("total", 0) for n in nodes)
    totals["standards_pass"] = sum(n["standards_summary"].get("pass", 0) for n in nodes)
    totals["standards_fail"] = sum(n["standards_summary"].get("fail", 0) for n in nodes)
    totals["standards_unknown"] = sum(n["standards_summary"].get("unknown", 0) for n in nodes)
    return {
        "schema": "oa.vps-app-inventory/1",
        "built_at": built_at,
        "source": "oa.vps-report/v1 installed_apps/apps + standards + safe inference",
        "supervision_source": "/ops/ · /api/ops/vps-fleet.json",
        "alias_policy": "Les alias d'inventaire restent visibles pour compatibilité, mais ne créent pas de VPS de supervision supplémentaire.",
        "aliases": aliases,
        "required_apps": REQUIRED_VPS_APPS,
        "totals": totals,
        "nodes": nodes,
    }


# ── Flotte VPS (vue multi-VPS /ops/, Fable rescue J4 07/07) ──────────────────
# Contrat : chaque VPS dépose un rapport oa.vps-report/v1 dans l'inbox inter-VPS.
# Le QG affiche qui rapporte, qui dérive (maturité FAIL) et qui est muet
# (rapport absent ou stale > 36 h) — un VPS muet est une alerte (doctrine H-Omar).

VPS_REPORT_FRESH_HOURS = 36

VPS_FLEET_EXPECTED = [
    {
        "node": "omar",
        "vps_id": "vps-omar",
        "label": "VPS-Omar — core OA",
        "transport_owner": "h-omar (cron local quotidien 06h30)",
        "expected_path": "/home/omar/11-Pilotage/sujets-actifs/inter-vps-inbox/omar/vps-report-latest.json",
    },
    {
        "node": "jab",
        "vps_id": "vps-jab",
        "label": "VPS-JAB — client JAB",
        "transport_owner": "cc-jab",
        "expected_path": "/home/omar/11-Pilotage/sujets-actifs/inter-vps-inbox/jab/vps-report-latest.json",
    },
    {
        "node": "pantheos",
        "vps_id": "vps-pantheos",
        "label": "Pantheos — famille alexgo.eu",
        "transport_owner": "h-aurel",
        "expected_path": "/home/omar/11-Pilotage/sujets-actifs/inter-vps-inbox/pantheos/vps-report-latest.json",
    },
]


def _parse_report_ts(value) -> dt.datetime | None:
    try:
        parsed = dt.datetime.fromisoformat(str(value or "").strip().replace("Z", "+00:00"))
    except Exception:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=dt.timezone.utc)


def _vps_fleet_node(expected: dict, report: dict | None, now: dt.datetime) -> dict:
    node: dict = dict(expected)
    node["expected"] = "transport_owner" in expected and bool(expected.get("expected_path"))
    if report is None:
        node["report_status"] = "missing"
        return node
    ts = _parse_report_ts(report.get("generated_at"))
    age_hours = round((now - ts).total_seconds() / 3600, 1) if ts else None
    fresh = age_hours is not None and 0 <= age_hours < VPS_REPORT_FRESH_HOURS
    standards = _standards_for_report(report)
    fails = [s for s in standards if s["verdict"] == "FAIL"]
    n_pass = sum(1 for s in standards if s["verdict"] == "PASS")
    raw_apps = [a for a in (report.get("apps") or []) if isinstance(a, dict)]
    partial = not standards
    if not raw_apps:
        raw_apps = [a for a in (report.get("installed_apps") or []) if isinstance(a, dict)]
    kinds: dict[str, int] = {}
    for app in raw_apps:
        kind = str(app.get("kind") or "autre")
        kinds[kind] = kinds.get(kind, 0) + 1
    maturity = str(report.get("maturity") or "").upper()
    if maturity not in {"PASS", "FAIL", "UNKNOWN"}:
        maturity = "FAIL" if fails else ("PASS" if standards else "UNKNOWN")
    next_action = report.get("next_action") if isinstance(report.get("next_action"), dict) else {}
    node.update({
        "report_status": "fresh" if fresh else "stale",
        "vps_id": str(report.get("vps_id") or expected.get("vps_id") or f'vps-{expected["node"]}'),
        "tenant": str(report.get("tenant") or "unknown"),
        "generated_at": str(report.get("generated_at") or "unknown"),
        "age_hours": age_hours,
        "source_path": str(report.get("_source_path") or ""),
        "maturity": maturity,
        "partial": partial,  # rapport reçu mais sans standards[] → maturité invérifiable
        "standards_pass": n_pass,
        "standards_fail": len(fails),
        "standards_total": len(standards),
        "standards_pass_pct": round(n_pass / len(standards) * 100) if standards else None,
        "fails": [{"item_id": s["item_id"], "proof_redacted": s["evidence"]} for s in fails],
        "apps_total": len(raw_apps),
        "apps_by_kind": dict(sorted(kinds.items(), key=lambda kv: -kv[1])),
        "next_action": {
            "owner": str(next_action.get("owner") or "unknown"),
            "action_1_line": str(next_action.get("action_1_line") or "non renseignée"),
        },
    })
    return node


# oa-master = flux santé h-omar du MÊME VPS que vps-omar (rapport OmarTop) :
# on ne le compte pas comme un 4e VPS, le bloc omar fait foi.
VPS_FLEET_ALIAS_NODES = {"oa-master"}


def collect_vps_fleet(built_at: str) -> dict:
    """Vue flotte /ops/ : un bloc par VPS attendu + les nœuds surprises de l'inbox."""
    now = _parse_report_ts(built_at) or dt.datetime.now(dt.timezone.utc)
    reports = {r["node"]: r for r in _read_inter_vps_reports()}
    expected_nodes = {e["node"] for e in VPS_FLEET_EXPECTED}
    nodes = [_vps_fleet_node(e, reports.get(e["node"]), now) for e in VPS_FLEET_EXPECTED]
    for extra in sorted(set(reports) - expected_nodes - VPS_FLEET_ALIAS_NODES):
        nodes.append(_vps_fleet_node(
            {"node": extra, "vps_id": f"vps-{extra}", "label": f"{extra} — hors flotte attendue",
             "transport_owner": "inconnu", "expected_path": ""},
            reports[extra], now,
        ))
    reporting = sum(1 for n in nodes if n["report_status"] == "fresh")
    en_derive = sum(1 for n in nodes if n["report_status"] == "fresh" and n.get("maturity") == "FAIL")
    muets = sum(1 for n in nodes if n["report_status"] in {"missing", "stale"})
    return {
        "schema": "oa.vps-fleet-status/1",
        "built_at": built_at,
        "source": "oa.vps-report/v1 (inbox inter-VPS) · fraîcheur attendue < 36 h",
        "fresh_hours": VPS_REPORT_FRESH_HOURS,
        "summary": {
            "expected": len(VPS_FLEET_EXPECTED),
            "nodes": len(nodes),
            "reporting": reporting,
            "en_derive": en_derive,
            "muets": muets,
            "standards_fail": sum(int(n.get("standards_fail") or 0) for n in nodes),
        },
        "sav": "non instrumenté — aucun flux SAV n'existe encore",
        "nodes": nodes,
    }


# ── Hub node reports v1 → maturité QG synthétique ─────────────────────────────
# QG consomme les rapports Hub redacted. Il ne relit pas les logs locaux : si un
# rapport manque, le nœud reste UNKNOWN au lieu d'inférer un état depuis d'autres
# surfaces.
HUB_NODE_REPORT_DIRS = [
    Path("/home/omar/11-Pilotage/sujets-actifs/qg-hub-onboarding-reset/hub-node-reports"),
    Path("/home/omar/11-Pilotage/sujets-actifs/qg-hub-onboarding-reset/contracts/hub-node-report-v1/examples"),
    Path("/home/omar/.hermes/kanban/workspaces/t_11fc1a25/examples"),
]


def hub_node_report_dirs() -> list[Path]:
    """Return the sole Hub report source selected for this build mode.

    ``QG_HUB_NODE_REPORT_DIR`` is a candidate-smoke boundary: when set, QG
    reads only that directory (even if fixtures are enabled). An absent or
    invalid candidate directory therefore yields UNKNOWN rather than falling
    back to runtime reports or fixtures.
    """
    candidate_dir = os.environ.get("QG_HUB_NODE_REPORT_DIR")
    if candidate_dir:
        return [Path(candidate_dir)]
    if os.environ.get("QG_USE_TEST_FIXTURES") == "1":
        return [ROOT / "tests" / "fixtures" / "hub-node-reports"]
    return HUB_NODE_REPORT_DIRS


def build_output_dir() -> Path:
    """Return production public/ by default or an explicitly selected staging dir."""
    staging_dir = os.environ.get("QG_BUILD_OUTPUT_DIR")
    return Path(staging_dir) if staging_dir else PUBLIC

HUB_NODE_EXPECTED = [
    {"node_id": "oa-master", "label": "OA Master", "kind": "vps", "owner": "h-omar"},
    {"node_id": "pantheos", "label": "Pantheos", "kind": "family_host", "owner": "h-aurel"},
    {"node_id": "jab", "label": "JAB", "kind": "client_node", "owner": "cc-jab"},
    {"node_id": "h-local", "label": "H-local / PC Alex", "kind": "desktop", "owner": "h-local"},
]

PRIORITY_GAP_DOMAINS = {
    "backup_restore",
    "restore",
    "gateway",
    "secrets",
    "infisical",
    "observability",
    "disk_memory",
    "hub_local",
    "version_measurement",
    "runtime_hermes",
    "hermes_version",
    "hub_reporting",
}


def _hub_node_report_paths(root: Path) -> list[Path]:
    paths = set(root.glob("*.oa.hub-node-report.v1.json"))
    paths.update(root.glob("*hub-node-report*.json"))
    return sorted(paths)


def _hub_node_source_ref(node_id: str, path: Path) -> str:
    """Return a stable, public-safe reference for a consumed Hub node report."""
    suffix = path.name if path.name else "hub-node-report.v1.json"
    return f"oa.hub-node-report/v1:{node_id}:{suffix}"


def _read_hub_node_reports() -> dict[str, dict]:
    reports: dict[str, dict] = {}
    for root in hub_node_report_dirs():
        if not root.exists():
            continue
        for path in _hub_node_report_paths(root):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if not isinstance(payload, dict) or payload.get("schema") != "oa.hub-node-report/v1":
                continue
            node_block = payload.get("node") if isinstance(payload.get("node"), dict) else {}
            node_block = node_block or {}
            node_id = str(node_block.get("id") or payload.get("node_id") or path.name.split(".", 1)[0]).strip().lower()
            if not node_id:
                continue
            payload = dict(payload)
            payload["_source_ref"] = _hub_node_source_ref(node_id, path)
            prev = reports.get(node_id)
            if not prev or str(payload.get("generated_at") or "") >= str(prev.get("generated_at") or ""):
                reports[node_id] = payload
    return reports


def _priority_gaps(report: dict) -> list[dict]:
    gaps = []
    for raw in report.get("gaps") or []:
        if not isinstance(raw, dict):
            continue
        domain = str(raw.get("domain") or "unknown")
        if domain not in PRIORITY_GAP_DOMAINS:
            continue
        gaps.append({
            "priority": str(raw.get("priority") or "P1"),
            "domain": domain,
            "summary": str(raw.get("summary") or "gap non renseigné"),
        })
    return gaps


def _hub_node_summary(expected: dict, report: dict | None) -> dict:
    node_id = expected["node_id"]
    if report is None:
        return {
            **expected,
            "report_status": "missing",
            "status": "unknown",
            "score": None,
            "level": "unknown",
            "freshness": {"status": "unknown"},
            "source": {"kind": "absent", "mode": "unknown"},
            "source_path": "",
            "generated_at": "unknown",
            "hermes_version": {"current_version": "unknown", "upstream_status": "unknown", "gateway_status": {"status": "unknown"}},
            "domains": [],
            "priority_gaps": [{"priority": "P1", "domain": "hub_reporting", "summary": "rapport Hub node absent — QG affiche unknown"}],
            "next_action": {"owner": expected.get("owner", "unknown"), "label": "Publier oa.hub-node-report/v1 redacted"},
        }
    maturity = report.get("maturity") if isinstance(report.get("maturity"), dict) else {}
    maturity = maturity or {}
    freshness = report.get("freshness") if isinstance(report.get("freshness"), dict) else {}
    freshness = freshness or {}
    source = report.get("source") if isinstance(report.get("source"), dict) else {}
    source = source or {}
    hermes = report.get("hermes_version") if isinstance(report.get("hermes_version"), dict) else {}
    hermes = hermes or {}
    next_actions = [a for a in (report.get("next_actions") or []) if isinstance(a, dict)]
    first_action = next_actions[0] if next_actions else {}
    node_block = report.get("node") if isinstance(report.get("node"), dict) else {}
    node_block = node_block or {}
    return {
        **expected,
        "label": str(node_block.get("label") or expected.get("label") or node_id),
        "kind": str(node_block.get("kind") or expected.get("kind") or "unknown"),
        "hub_url": node_block.get("hub_url"),
        "report_status": "available",
        "status": str(report.get("status") or "unknown"),
        "score": maturity.get("score"),
        "level": str(maturity.get("level") or "unknown"),
        "freshness": {
            "status": str(freshness.get("status") or "unknown"),
            "checked_at": str(freshness.get("checked_at") or report.get("generated_at") or "unknown"),
            "max_age_seconds": freshness.get("max_age_seconds"),
        },
        "source": {"kind": str(source.get("kind") or "unknown"), "mode": str(source.get("mode") or "unknown"), "collector": str(source.get("collector") or "unknown")},
        "source_path": str(report.get("_source_ref") or ""),
        "generated_at": str(report.get("generated_at") or "unknown"),
        "hermes_version": {
            "current_version": str(hermes.get("current_version") or "unknown"),
            "upstream_status": str(hermes.get("upstream_status") or "unknown"),
            "install_mode": str(hermes.get("install_mode") or "unknown"),
            "gateway_status": hermes.get("gateway_status") if isinstance(hermes.get("gateway_status"), dict) else {"status": "unknown"},
        },
        "domains": [d for d in (maturity.get("domains") or []) if isinstance(d, dict)],
        "priority_gaps": _priority_gaps(report),
        "next_action": {
            "owner": str(first_action.get("owner") or expected.get("owner") or "unknown"),
            "label": str(first_action.get("label") or "prochaine action non renseignée"),
            "action_ref": str(first_action.get("action_ref") or "unknown"),
        },
    }


def collect_hub_node_maturity(built_at: str) -> dict:
    reports = _read_hub_node_reports()
    nodes = [_hub_node_summary(expected, reports.get(expected["node_id"])) for expected in HUB_NODE_EXPECTED]
    reporting = sum(1 for n in nodes if n["report_status"] == "available")
    return {
        "schema": "oa.qg.hub-node-maturity/1",
        "built_at": built_at,
        "source": "oa.hub-node-report/v1 redacted reports; no local logs duplicated",
        "freshness_policy": "QG affiche source/fraîcheur et unknown si source absente",
        "expected_nodes": [n["node_id"] for n in HUB_NODE_EXPECTED],
        "summary": {
            "expected": len(HUB_NODE_EXPECTED),
            "reporting": reporting,
            "missing": len(HUB_NODE_EXPECTED) - reporting,
            "unknown": sum(1 for n in nodes if n.get("status") == "unknown"),
            "avg_score": round(sum(int(n.get("score") or 0) for n in nodes if n.get("score") is not None) / reporting) if reporting else None,
            "priority_gaps": sum(len(n.get("priority_gaps") or []) for n in nodes),
        },
        "nodes": nodes,
    }



def _oa_action(action_id: str, mode: str, status: str, risk: str, label: str) -> dict:
    return {"id": action_id, "mode": mode, "status": status, "risk": risk, "label": label}


def _oa_page_contract(
    *,
    page_id: str,
    surface: str,
    route: str,
    url: str,
    objective: str,
    features: list[str],
    characteristics: list[str],
    source_of_truth: list[str],
    proofs: list[dict],
    actions: list[dict],
    owner: str,
    built_at: str,
    freshness_status: str = "fresh",
) -> dict:
    return {
        "id": page_id,
        "schema": "oa.page-contract/v1",
        "surface": surface,
        "route": route,
        "url": url,
        "objective": objective,
        "features": features,
        "characteristics": characteristics,
        "source_of_truth": source_of_truth,
        "proofs": proofs,
        "actions": actions,
        "owner": owner,
        "freshness": {"generated_at": built_at, "max_age": "24h", "status": freshness_status},
    }


def collect_oa_system_contracts(built_at: str) -> dict:
    """Shared QG/Hub/AppOmar contracts: visible pages, actions and proofs, public-safe."""
    common_proofs = [
        {"label": "QG live root", "url_or_path": "https://qg.omar.paris/", "checked_at": built_at, "status": "ok"},
        {"label": "Hub live root", "url_or_path": "https://hub.omar.paris/", "checked_at": built_at, "status": "ok"},
        {"label": "AppOmar audit live", "url_or_path": "https://app.omar.paris/audit/", "checked_at": built_at, "status": "ok"},
        {"label": "Mission source", "url_or_path": "11-Pilotage/sujets-actifs/2026-07-09-oa-qg-hub-app-systeme-vivant/NIGHT-MISSION.md", "checked_at": built_at, "status": "ok"},
    ]
    actions = [
        _oa_action("qg.smoke", "check", "enabled", "low", "Smoker QG/Hub/AppOmar et rafraîchir les preuves"),
        _oa_action("hub.runtime.plan", "plan", "enabled", "low", "Planifier correction locale Hub depuis les JSON runtime"),
        _oa_action("appomar.lifecycle.review", "check", "enabled", "low", "Vérifier que le tunnel AppOmar reste honnête audit→SAV"),
        _oa_action("oa.production.apply", "apply", "gated", "high", "Appliquer en production seulement après gate H-Athena + arbitrage H-Omar"),
    ]
    pages = [
        _oa_page_contract(page_id="qg.control", surface="qg", route="/controle-oa/", url="https://qg.omar.paris/controle-oa/", objective="Piloter globalement les applications OA: objectifs, preuves, actions, gates, PR et liens Hub/AppOmar.", features=["registry Apps OA", "preuves timestampées", "actions check/plan/apply-gated", "liens QG→Hub→AppOmar"], characteristics=["global", "lecture-first", "no secrets", "source/freshness visibles"], source_of_truth=["scripts/build.py", "public/api/oa-system-contracts.json", "NIGHT-MISSION.md"], proofs=common_proofs[:1] + common_proofs[3:], actions=[actions[0], actions[3]], owner="H-Omar", built_at=built_at),
        _oa_page_contract(page_id="hub.home", surface="hub", route="/", url="https://hub.omar.paris/", objective="Cockpit local du VPS/tenant: apps installées, connexions, santé, maturité, actions locales.", features=["identité VPS", "apps locales groupées", "connexions", "maturité OmarTop", "actions locales"], characteristics=["local-first", "Hub owner vérité runtime", "check/plan visibles", "apply désactivé sans backend gate"], source_of_truth=["public/api/sites.json", "public/api/apps.json", "public/api/maturity-runtime.json", "public/api/oa-system-contracts.json"], proofs=[common_proofs[1]], actions=[actions[1], actions[3]], owner="H-Omar", built_at=built_at),
        _oa_page_contract(page_id="hub.actions", surface="hub", route="/parametres/actions", url="https://hub.omar.paris/parametres/actions", objective="Lister les actions pilotables du Hub avec statut, risque et garde-fous.", features=["catalogue actions", "modes check/plan/apply", "risques", "gates"], characteristics=["apply-gated", "pas d'action destructive aveugle", "preuves attendues"], source_of_truth=["public/api/settings-status.json", "public/api/maturity-runtime.json"], proofs=[{"label": "Hub actions live", "url_or_path": "https://hub.omar.paris/parametres/actions", "checked_at": built_at, "status": "ok"}], actions=[actions[0], actions[1], actions[3]], owner="H-Omar", built_at=built_at),
        _oa_page_contract(page_id="appomar.lifecycle", surface="appomar", route="/audit/", url="https://app.omar.paris/audit/", objective="Parcours client: promesse → audit conversationnel → rapport/propositions → devis/validation → onboarding → Hub client → SAV.", features=["audit conversationnel", "rapport structuré", "devis justifié", "onboarding prérempli", "SAV"], characteristics=["public/commercial", "paiement non modifié sans GO", "secrets interdits", "statut live honnête"], source_of_truth=["docs/contracts/appomar-activation-boundary-v1.md", "src/audit_tree.business_tech.v1.yaml", "public/api/appomar-lifecycle.json"], proofs=[common_proofs[2]], actions=[actions[2], actions[3]], owner="H-Omar", built_at=built_at),
        _oa_page_contract(page_id="omartop.standards", surface="omartop", route="/", url="https://top.omar.paris/", objective="Référence standards et maturité OA, consommée par QG et Hub.", features=["standards", "maturité", "gaps", "prochaines actions"], characteristics=["référentiel", "versionné", "non cockpit runtime"], source_of_truth=["OmarTop", "Hub public/api/maturity-runtime.json"], proofs=[{"label": "OmarTop link", "url_or_path": "https://top.omar.paris/", "checked_at": built_at, "status": "partial"}], actions=[actions[0]], owner="H-Omar", built_at=built_at, freshness_status="unknown"),
        _oa_page_contract(page_id="hermesui.kanban", surface="qg", route="/kanban", url="http://100.79.68.6:9119/kanban", objective="Pilotage quotidien des cartes agents via HermesUI/Kanban.", features=["cartes", "statuts", "résultats persistés"], characteristics=["interne tailnet", "résultat kanban obligatoire", "pas OWUI"], source_of_truth=["HermesUI kanban.db", "H-Omar memory"], proofs=[{"label": "URL Kanban canonique", "url_or_path": "http://100.79.68.6:9119/kanban", "checked_at": built_at, "status": "partial"}], actions=[actions[0]], owner="H-Omar", built_at=built_at, freshness_status="unknown"),
    ]
    apps = [
        {"id": "qg", "name": "QG", "surface": "qg", "url": "https://qg.omar.paris/", "objective": pages[0]["objective"], "status": "live"},
        {"id": "hub", "name": "OmarHub", "surface": "hub", "url": "https://hub.omar.paris/", "objective": pages[1]["objective"], "status": "live"},
        {"id": "appomar", "name": "AppOmar", "surface": "appomar", "url": "https://app.omar.paris/audit/", "objective": pages[3]["objective"], "status": "live_audit_only"},
        {"id": "omartop", "name": "OmarTop", "surface": "omartop", "url": "https://top.omar.paris/", "objective": pages[4]["objective"], "status": "referenced"},
        {"id": "catalogue", "name": "Catalogue", "surface": "catalogue", "url": "https://catalogue.omar.paris/", "objective": "Référentiel des briques apps/agents/tools OA.", "status": "referenced"},
        {"id": "lab", "name": "Lab", "surface": "lab", "url": "https://lab.omar.paris/", "objective": "Atelier projets et prototypes OA.", "status": "live"},
        {"id": "kanban", "name": "HermesUI Kanban", "surface": "qg", "url": "http://100.79.68.6:9119/kanban", "objective": "Pilotage des cartes agents.", "status": "internal"},
    ]
    return {
        "schema": "oa.system-contracts/v1",
        "generated_at": built_at,
        "visibility": "public_safe_redacted",
        "contracts": ["oa.app-registry/v1", "oa.page-contract/v1", "oa.action-catalog/v1", "oa.automation-registry/v1", "oa.proof-ledger/v1"],
        "app_registry": {"schema": "oa.app-registry/v1", "items": apps},
        "page_contracts": {"schema": "oa.page-contract/v1", "items": pages},
        "action_catalog": {"schema": "oa.action-catalog/v1", "items": actions},
        "automation_registry": {"schema": "oa.automation-registry/v1", "items": [
            {"id": "qg.rebuild", "surface": "qg", "mode": "check", "status": "enabled", "cadence": "manual_or_cron", "proof": "/api/core-repos.json"},
            {"id": "hub.runtime.refresh", "surface": "hub", "mode": "check", "status": "enabled", "cadence": "manual_or_cron", "proof": "/api/health.json"},
            {"id": "prod.apply", "surface": "qg", "mode": "apply", "status": "gated", "cadence": "human_gate", "proof": "review_result.json pass/pass_with_nits required"},
        ]},
        "proof_ledger": {"schema": "oa.proof-ledger/v1", "items": common_proofs},
        "safety": {"forbidden": ["secrets", "raw_env", "auth_headers", "raw_transcripts", "private_keys"], "apply_policy": "apply actions gated/disabled unless backend + H-Athena review gate exists"},
    }


def page_oa_system_control(contracts: dict) -> str:
    pages = (contracts.get("page_contracts") or {}).get("items") or []
    apps = (contracts.get("app_registry") or {}).get("items") or []
    actions = (contracts.get("action_catalog") or {}).get("items") or []
    html = '<section class="mb-6"><div class="text-xs font-semibold uppercase tracking-wide text-blue-600">Contrôle global OA</div><h1 class="text-2xl font-bold text-slate-950">QG / Hub / AppOmar — objectifs, preuves, actions</h1><p class="mt-1 text-sm text-slate-500">Contrat partagé <span class="font-mono">oa.system-contracts/v1</span> · public-safe · apply gated.</p></section>'
    html += '<div class="grid md:grid-cols-4 gap-3 mb-6">'
    html += f'<a href="/api/oa-system-contracts.json" class="rounded-xl border border-blue-200 bg-blue-50 px-4 py-3"><div class="text-xs text-blue-700">API contrat</div><div class="text-lg font-bold text-blue-950">{escape(contracts.get("schema", "unknown"))}</div></a>'
    html += f'<div class="rounded-xl border border-slate-200 bg-white px-4 py-3"><div class="text-xs text-slate-500">Apps</div><div class="text-2xl font-bold text-slate-900">{len(apps)}</div></div>'
    html += f'<div class="rounded-xl border border-slate-200 bg-white px-4 py-3"><div class="text-xs text-slate-500">Pages</div><div class="text-2xl font-bold text-slate-900">{len(pages)}</div></div>'
    html += f'<div class="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3"><div class="text-xs text-amber-700">Policy</div><div class="text-sm font-bold text-amber-900">apply gated</div></div></div>'
    html += '<section class="grid lg:grid-cols-2 gap-4 mb-6">'
    for page in pages:
        proofs = page.get("proofs") or []
        page_actions = page.get("actions") or []
        html += '<article class="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">'
        html += f'<div class="flex items-start justify-between gap-3"><div><div class="text-xs font-semibold uppercase tracking-wide text-blue-600">{escape(str(page.get("surface")))}</div><h2 class="text-lg font-bold text-slate-950">{escape(str(page.get("id")))}</h2></div><a class="text-xs text-blue-600 hover:underline" href="{escape(str(page.get("url")))}">ouvrir</a></div>'
        html += f'<p class="mt-2 text-sm text-slate-700">{escape(str(page.get("objective")))}</p>'
        html += '<div class="mt-3 flex flex-wrap gap-2">' + ''.join(f'<span class="rounded-full bg-slate-100 px-2 py-1 text-xs text-slate-600">{escape(str(x))}</span>' for x in (page.get("features") or [])[:5]) + '</div>'
        html += '<div class="mt-3 text-xs text-slate-500">Sources: ' + escape(', '.join(map(str, page.get("source_of_truth") or []))) + '</div>'
        html += '<div class="mt-3 space-y-1"><div class="text-xs font-semibold text-slate-700">Preuves</div>' + ''.join(f'<div class="text-xs text-slate-600">{escape(str(p.get("status")))} · {escape(str(p.get("label")))} · <span class="font-mono">{escape(str(p.get("url_or_path")))}</span></div>' for p in proofs[:3]) + '</div>'
        html += '<div class="mt-3 space-y-1"><div class="text-xs font-semibold text-slate-700">Actions</div>' + ''.join(f'<div class="text-xs text-slate-600"><span class="font-mono">{escape(str(a.get("mode")))}</span> · {escape(str(a.get("status")))} · {escape(str(a.get("label") or a.get("id")))}</div>' for a in page_actions[:3]) + '</div>'
        html += f'<div class="mt-3 text-[11px] text-slate-400">owner {escape(str(page.get("owner")))} · generated {escape(str((page.get("freshness") or {}).get("generated_at")))}</div>'
        html += '</article>'
    html += '</section>'
    html += '<section class="rounded-2xl border border-slate-200 bg-white p-4"><h2 class="text-sm font-bold text-slate-950">Catalogue actions global</h2><div class="mt-3 grid md:grid-cols-2 gap-2">'
    for action in actions:
        cls = 'bg-red-50 text-red-700 border-red-100' if action.get('mode') == 'apply' else 'bg-green-50 text-green-700 border-green-100' if action.get('mode') == 'check' else 'bg-blue-50 text-blue-700 border-blue-100'
        html += f'<div class="rounded-xl border {cls} px-3 py-2 text-xs"><span class="font-mono">{escape(str(action.get("id")))}</span> · {escape(str(action.get("mode")))} · {escape(str(action.get("status")))} · risque {escape(str(action.get("risk")))}</div>'
    html += '</div></section>'
    return html


def collect_qg_cockpit(*, built_at: str, decisions: list, blocages: dict, agent_activity: dict, agent_loop_audit: dict, contracts: dict, core_data: dict) -> dict:
    """Cockpit QG public-safe: décisions, preuves, agents et fraîcheur.

    Le QG ne réplique pas Hub/OmarTop : il publie seulement des compteurs, liens
    vers les sources de vérité et fraîcheur des snapshots qu'il affiche.
    """
    open_decisions = [d for d in decisions if isinstance(d, dict) and d.get("statut") == "ouverte"]
    blocages_compteurs = blocages.get("compteurs", {}) if isinstance(blocages, dict) else {}
    activity_summary = agent_activity.get("summary", {}) if isinstance(agent_activity, dict) else {}
    audit_summary = agent_loop_audit.get("summary", {}) if isinstance(agent_loop_audit, dict) else {}
    proof_items = ((contracts.get("proof_ledger") or {}).get("items") or []) if isinstance(contracts, dict) else []
    pages = ((contracts.get("page_contracts") or {}).get("items") or []) if isinstance(contracts, dict) else []

    def freshness(name: str, source: str, generated_at: object, href: str, status: str = "fresh", note: str = "") -> dict:
        return {
            "name": name,
            "source": source,
            "generated_at": str(generated_at or "unknown"),
            "status": status if generated_at not in (None, "", "unknown") else "unknown",
            "href": href,
            "note": note,
        }

    return {
        "schema": "oa.qg-cockpit/v1",
        "generated_at": built_at,
        "mode": "read-only-pointer-ledger",
        "boundary": {
            "qg": "cockpit global: compte, pointe, expose preuves/fraîcheur",
            "hub": "runtime local par VPS/tenant — QG ne duplique pas ses données fines",
            "omartop": "standards/maturité — QG ne remplace pas le référentiel",
        },
        "summary": {
            "open_decisions": len(open_decisions),
            "alex_blockers": int(blocages_compteurs.get("pour_alex") or 0),
            "total_blockers": int(blocages_compteurs.get("total") or blocages_compteurs.get("ouverts") or 0),
            "proofs": len(proof_items),
            "agent_tasks_active": int(activity_summary.get("active") or 0),
            "agent_tasks_blocked": int(activity_summary.get("blocked") or 0),
            "agents_seen": int(activity_summary.get("agents") or 0),
            "gate_orphans": int(audit_summary.get("total_orphans") or 0),
        },
        "decisions": [
            {
                "id": str(d.get("id") or ""),
                "group": str(d.get("groupe") or "divers"),
                "label": str(d.get("texte") or "Décision ouverte")[:220],
                "href": f"/decisions/#card-{d.get('id')}",
                "blocked_ref": str(d.get("blocked_ref") or ""),
            }
            for d in open_decisions[:8]
        ],
        "proofs": [
            {
                "label": str(p.get("label") or "preuve"),
                "status": str(p.get("status") or "unknown"),
                "ref": str(p.get("url_or_path") or ""),
                "checked_at": str(p.get("checked_at") or built_at),
            }
            for p in proof_items[:10]
            if isinstance(p, dict)
        ],
        "agents": {
            "summary": activity_summary,
            "decision_required": (agent_activity.get("decision_required") or [])[:8] if isinstance(agent_activity, dict) else [],
            "by_status": activity_summary.get("by_status") or {},
            "by_type": activity_summary.get("by_type") or {},
        },
        "freshness": [
            freshness("QG core repos", "/api/core-repos.json", core_data.get("built_at"), "/api/core-repos.json"),
            freshness("Décisions", "var/decisions.json → /api/decisions.json", built_at if decisions else None, "/decisions/", "fresh" if decisions else "unknown"),
            freshness("Blocages", "collect_blocages.py → /api/blocages.json", blocages.get("generated_at") if isinstance(blocages, dict) else None, "/blocages/"),
            freshness("Agents", "scripts/agent_activity.py → /api/agent-activity.json", agent_activity.get("generated_at") if isinstance(agent_activity, dict) else None, "/agent-activity/"),
            freshness("Gates & orphelins", "var/agent-loop-audit.json → /api/agent-loop-audit.json", agent_loop_audit.get("checked_at") if isinstance(agent_loop_audit, dict) else None, "/agent-loop/", note="peut être figé depuis le 15/06 si non recronifié"),
            freshness("Contrats pages", "/api/oa-system-contracts.json", contracts.get("generated_at") if isinstance(contracts, dict) else None, "/controle-oa/"),
        ],
        "pages": [
            {"id": str(p.get("id") or ""), "route": str(p.get("route") or ""), "freshness": p.get("freshness") or {}}
            for p in pages[:12]
            if isinstance(p, dict)
        ],
    }


def page_qg_cockpit(cockpit: dict) -> str:
    summary = cockpit.get("summary", {}) if isinstance(cockpit, dict) else {}
    decisions = cockpit.get("decisions", []) if isinstance(cockpit, dict) else []
    proofs = cockpit.get("proofs", []) if isinstance(cockpit, dict) else []
    freshness = cockpit.get("freshness", []) if isinstance(cockpit, dict) else []
    boundary = cockpit.get("boundary", {}) if isinstance(cockpit, dict) else {}
    agents = cockpit.get("agents", {}) if isinstance(cockpit, dict) else {}

    def kpi(label: str, value: object, href: str, tone: str = "text-slate-950") -> str:
        return f'<a href="{escape(href)}" class="block rounded-xl border border-slate-200 bg-white px-4 py-3 hover:border-blue-300 hover:shadow-sm"><div class="text-2xl font-bold {tone}">{escape(str(value))}</div><div class="text-xs text-slate-500 mt-0.5">{escape(label)}</div></a>'

    def status_cls(status: object) -> str:
        return {"fresh": "bg-green-50 text-green-700 border-green-200", "ok": "bg-green-50 text-green-700 border-green-200", "partial": "bg-amber-50 text-amber-700 border-amber-200", "unknown": "bg-slate-50 text-slate-600 border-slate-200", "stale": "bg-red-50 text-red-700 border-red-200"}.get(str(status), "bg-slate-50 text-slate-600 border-slate-200")

    decision_rows = "".join(
        '<a class="block px-4 py-3 border-b border-slate-100 last:border-0 hover:bg-amber-50" href="{href}"><div class="text-sm font-semibold text-slate-900">{label}</div><div class="mt-1 text-xs text-slate-500">{group}{blocked}</div></a>'.format(
            href=escape(str(d.get("href") or "/decisions/")),
            label=escape(str(d.get("label") or "Décision ouverte")),
            group=escape(str(d.get("group") or "divers")),
            blocked=(" · bloque " + escape(str(d.get("blocked_ref")))) if d.get("blocked_ref") else "",
        )
        for d in decisions
    ) or '<div class="px-4 py-4 text-sm text-green-700 bg-green-50">Aucune décision ouverte dans le snapshot.</div>'

    proof_rows = "".join(
        '<div class="px-4 py-3 border-b border-slate-100 last:border-0"><div class="flex items-start justify-between gap-2"><div class="text-sm font-semibold text-slate-900">{label}</div><span class="rounded-full border px-2 py-0.5 text-[11px] font-semibold {cls}">{status}</span></div><div class="mt-1 text-xs font-mono text-slate-500 break-all">{ref}</div><div class="text-[11px] text-slate-400 mt-0.5">check {checked}</div></div>'.format(
            label=escape(str(p.get("label") or "preuve")),
            cls=status_cls(p.get("status")),
            status=escape(str(p.get("status") or "unknown")),
            ref=escape(str(p.get("ref") or "")),
            checked=escape(str(p.get("checked_at") or "unknown")),
        )
        for p in proofs
    ) or '<div class="px-4 py-4 text-sm text-amber-700 bg-amber-50">Aucune preuve publiée.</div>'

    freshness_rows = "".join(
        '<a href="{href}" class="grid md:grid-cols-[180px_1fr_170px_90px] gap-2 px-4 py-3 border-b border-slate-100 last:border-0 hover:bg-slate-50"><div class="text-sm font-semibold text-slate-900">{name}</div><div class="text-xs text-slate-500">{source}{note}</div><div class="text-xs font-mono text-slate-500">{generated}</div><div><span class="rounded-full border px-2 py-0.5 text-[11px] font-semibold {cls}">{status}</span></div></a>'.format(
            href=escape(str(f.get("href") or "#")),
            name=escape(str(f.get("name") or "source")),
            source=escape(str(f.get("source") or "")),
            note=(" · " + escape(str(f.get("note")))) if f.get("note") else "",
            generated=escape(str(f.get("generated_at") or "unknown")),
            cls=status_cls(f.get("status")),
            status=escape(str(f.get("status") or "unknown")),
        )
        for f in freshness
    )

    by_status = agents.get("by_status") or {}
    by_type = agents.get("by_type") or {}
    agent_summary = f'<div class="rounded-xl border border-slate-200 bg-slate-50 px-4 py-3 text-xs text-slate-600"><span class="font-semibold">Statuts:</span> {escape(str(by_status))} · <span class="font-semibold">Types:</span> {escape(str(by_type))}</div>'

    return (
        '<section class="mb-6"><div class="text-xs font-semibold uppercase tracking-wide text-blue-600">Cockpit décision/proof/agents</div><h1 class="text-2xl font-bold text-slate-950">Décider, prouver, rafraîchir — sans dupliquer Hub/OmarTop</h1><p class="mt-1 text-sm text-slate-500">Le QG compte et pointe: décisions ouvertes, preuves publiées, activité agents et fraîcheur des sources. API <a class="text-blue-600 hover:underline" href="/api/qg-cockpit.json">oa.qg-cockpit/v1</a>.</p></section>'
        '<div class="grid grid-cols-2 lg:grid-cols-4 gap-3 mb-5">'
        + kpi("Décisions ouvertes", summary.get("open_decisions", 0), "/decisions/", "text-amber-600" if summary.get("open_decisions") else "text-slate-950")
        + kpi("Blocages Alex", summary.get("alex_blockers", 0), "/blocages/", "text-red-600" if summary.get("alex_blockers") else "text-slate-950")
        + kpi("Preuves ledger", summary.get("proofs", 0), "/controle-oa/")
        + kpi("Agents actifs", summary.get("agent_tasks_active", 0), "/agent-activity/")
        + '</div><section class="grid lg:grid-cols-3 gap-4 mb-5">'
        '<article class="rounded-2xl border border-amber-200 bg-white overflow-hidden"><div class="px-4 py-3 bg-amber-50 border-b border-amber-100"><div class="text-sm font-bold text-amber-950">Décisions</div><div class="text-xs text-amber-700">Lien vers /decisions/, pas de recomptage parallèle.</div></div>' + decision_rows + '</article>'
        '<article class="rounded-2xl border border-blue-200 bg-white overflow-hidden"><div class="px-4 py-3 bg-blue-50 border-b border-blue-100"><div class="text-sm font-bold text-blue-950">Proof ledger</div><div class="text-xs text-blue-700">Preuves timestampées, public-safe.</div></div>' + proof_rows + '</article>'
        '<article class="rounded-2xl border border-slate-200 bg-white p-4"><div class="text-sm font-bold text-slate-950">Agents & gates</div><div class="mt-2 grid grid-cols-2 gap-2">'
        + kpi("Bloquées", summary.get("agent_tasks_blocked", 0), "/agent-activity/", "text-red-600" if summary.get("agent_tasks_blocked") else "text-slate-950")
        + kpi("Orphelins gate", summary.get("gate_orphans", 0), "/agent-loop/", "text-red-600" if summary.get("gate_orphans") else "text-slate-950")
        + '</div><div class="mt-3">' + agent_summary + '</div></article></section>'
        '<section class="rounded-2xl border border-slate-200 bg-white overflow-hidden mb-5"><div class="px-4 py-3 border-b border-slate-100"><div class="text-sm font-bold text-slate-950">Fraîcheur des sources affichées</div><div class="text-xs text-slate-400">unknown vaut mieux qu\'une donnée prétendue live.</div></div>' + freshness_rows + '</section>'
        '<section class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 text-xs text-slate-600"><span class="font-semibold">Boundary:</span> QG — ' + escape(str(boundary.get("qg"))) + ' · Hub — ' + escape(str(boundary.get("hub"))) + ' · OmarTop — ' + escape(str(boundary.get("omartop"))) + '</section>'
    )


def payload(built_at: str) -> dict:
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
        live["ovh"] = ovh_live(_vault_read("secret/integrations/ovh").data)
    else:
        live["ovh"] = {"domains": [], "email_domains_with_accounts": []}

    fleet_result = hetzner_fleet_result()
    fleet = fleet_result["items"]
    fleet_supervision_v0 = _read_var_json("oa-fleet-supervision-v0.json")
    if not isinstance(fleet_supervision_v0, dict):
        fleet_supervision_v0 = {}
    # Enrichit la supervision flotte avec la conformité graduée 4 couleurs (Omar).
    _inject_graded_conformity(fleet_supervision_v0)
    vps_app_inventory = collect_vps_app_inventory(built_at)
    resource_onboarding_raw = _read_var_json("vps-resource-onboarding-v0.json")
    if not isinstance(resource_onboarding_raw, dict):
        resource_onboarding_raw = {}
    # Public QG data object backs /api/core-repos.json as well as page render.
    # Never carry the internal resource-onboarding payload into that object:
    # it may include local paths/source names that are useful to builders but
    # forbidden on public/API surfaces.
    resource_onboarding = sanitize_resource_onboarding_public(resource_onboarding_raw)
    return {
        "version": VERSION, "domain": DOMAIN, "built_at": built_at,
        "items": items, "counts": counts,
        "catalog": CATALOG, "providers": providers, "live": live,
        "fleet": fleet,
        "fleet_status": fleet_result["status"],
        "fleet_supervision_v0": fleet_supervision_v0,
        "vps": vps,
        "vps_app_inventory": vps_app_inventory,
        "resource_onboarding": resource_onboarding,
        "triage": {"built_at": triage.get("built_at"), "llm_used": triage.get("llm_used"),
                   "top3": triage.get("top3", [])},
    }


# ── HTML layout ───────────────────────────────────────────────────────────────

TAILWIND = "https://cdn.tailwindcss.com"
FONTS    = "https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap"

ICON_DOC = 'M12 6.042A8.967 8.967 0 0 0 6 3.75c-1.052 0-2.062.18-3 .512v14.25A8.987 8.987 0 0 1 6 18c2.305 0 4.408.867 6 2.292m0-14.25a8.966 8.966 0 0 1 6-2.292c1.052 0 2.062.18 3 .512v14.25A8.987 8.987 0 0 0 18 18a8.967 8.967 0 0 0-6 2.292m0-14.25v14.25'
ICON_MAP = 'M9 6.75V15m6-6v8.25m.503 3.498 4.875-2.437c.381-.19.622-.58.622-1.006V4.82c0-.836-.88-1.38-1.628-1.006l-3.869 1.934c-.317.159-.69.159-1.006 0L9.503 3.252a1.125 1.125 0 0 0-1.006 0L3.622 5.689C3.24 5.88 3 6.27 3 6.695V19.18c0 .836.88 1.38 1.628 1.006l3.869-1.934c.317-.159.69-.159 1.006 0l4.994 2.497c.317.158.69.158 1.006 0Z'
ICON_GRID = 'M3.75 12h16.5m-16.5 3.75h16.5M3.75 19.5h16.5M5.625 4.5h12.75a1.875 1.875 0 0 1 0 3.75H5.625a1.875 1.875 0 0 1 0-3.75Z'
ICON_STOP = 'M18.364 18.364A9 9 0 0 0 5.636 5.636m12.728 12.728A9 9 0 0 1 5.636 5.636m12.728 12.728L5.636 5.636'
ICON_TOOLS = 'M11.42 15.17 17.25 21A2.652 2.652 0 0 0 21 17.25l-5.877-5.877M11.42 15.17l2.496-3.03c.317-.384.74-.626 1.208-.766M11.42 15.17l-4.655 5.653a2.548 2.548 0 1 1-3.586-3.586l6.837-5.63m5.108-.233c.55-.164 1.163-.188 1.743-.14a4.5 4.5 0 0 0 4.486-6.336l-3.276 3.277a3.004 3.004 0 0 1-2.25-2.25l3.276-3.276a4.5 4.5 0 0 0-6.336 4.486c.091 1.076-.071 2.264-.904 2.95l-.102.085m-1.745 1.437L5.909 7.5H4.5L2.25 3.75l1.5-1.5L7.5 4.5v1.409l4.26 4.26m-1.745 1.437 1.745-1.437m6.615 8.206L15.75 15.75M4.867 19.125h.008v.008h-.008v-.008Z'
ICON_LOOP = 'M3.75 12a8.25 8.25 0 0 1 14.49-5.42M20.25 6.75v-4.5m0 4.5h-4.5M20.25 12a8.25 8.25 0 0 1-14.49 5.42M3.75 17.25v4.5m0-4.5h4.5'
ICON_CHART = 'M3 13.125C3 12.504 3.504 12 4.125 12h2.25c.621 0 1.125.504 1.125 1.125v6.75C7.5 20.496 6.996 21 6.375 21h-2.25A1.125 1.125 0 0 1 3 19.875v-6.75ZM9.75 8.625c0-.621.504-1.125 1.125-1.125h2.25c.621 0 1.125.504 1.125 1.125v11.25c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 0 1-1.125-1.125V8.625ZM16.5 4.125C16.5 3.504 17.004 3 17.625 3h2.25C20.496 3 21 3.504 21 4.125v15.75c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 0 1-1.125-1.125V4.125Z'
ICON_CLOCK = 'M12 6v6h4.5m4.5 0a9 9 0 1 1-18 0 9 9 0 0 1 18 0Z'

NAV_SECTIONS = [
    {
        "key": "commandement",
        "label": "Commandement",
        "href": "/",
        "icon": ICON_GRID,
        "hint": "Décider maintenant",
        "children": [
            ("/", "registry", "Accueil"),
            ("/cockpit/", "cockpit", "Cockpit"),
            ("/productivite/", "productivite", "Objectif du jour"),
            ("/blocages/", "blocages", "Blocages"),
            ("/decisions/", "decisions", "Décisions"),
        ],
    },
    {
        "key": "production",
        "label": "Production",
        "href": "/chantiers/",
        "icon": ICON_TOOLS,
        "hint": "Missions et livraisons",
        "children": [
            ("/chantiers/", "chantiers", "Chantiers"),
            ("/agent-activity/", "agent-activity", "Activité agents"),
            ("/agent-loop/", "agent-loop", "Gates & orphelins"),
            ("/builds/", "builds", "Builds"),
        ],
    },
    {
        "key": "supervision",
        "label": "Supervision",
        "href": "/ops/",
        "icon": ICON_CHART,
        "hint": "Fleet, clients, apps",
        "children": [
            ("/ops/", "ops", "Ops"),
            ("/controle-oa/", "controle-oa", "Contrôle OA"),
            ("/clients/", "clients", "Clients & VPS"),
            ("/apps/qg/", "app-qg", "Fiche QG"),
            ("/apps/hub/", "app-hub", "Fiche Hub"),
            ("/apps/app/", "app-app", "Fiche AppOmar"),
        ],
    },
    {
        "key": "standards",
        "label": "Standards",
        "href": "/manifeste/",
        "icon": ICON_DOC,
        "hint": "OmarTop et doctrine",
        "children": [
            ("/manifeste/", "manifeste", "Manifeste"),
            ("/docs/", "docs", "Docs"),
            ("/carte/", "carte", "Carte"),
            ("/partenaires/", "partenaires", "Partenaires"),
            ("/apps/omartop/", "app-omartop", "Fiche OmarTop"),
        ],
    },
    {
        "key": "journal",
        "label": "Journal",
        "href": "/changelog/",
        "icon": ICON_CLOCK,
        "hint": "Historique et legacy",
        "children": [
            ("/objectifs/", "objectifs", "Objectifs legacy"),
            ("/changelog/", "changelog", "Changelog"),
            ("/apps/landing/", "app-landing", "Fiche Landing"),
            ("/apps/catalogue/", "app-catalogue", "Fiche Catalogue"),
            ("/apps/lab/", "app-lab", "Fiche Lab"),
        ],
    },
]

# Compat: anciens tests / helpers peuvent encore itérer NAV_ITEMS.
NAV_ITEMS = [
    (href, key, label, ICON_GRID)
    for section in NAV_SECTIONS
    for href, key, label in section["children"]
]


def _active_section(active: str) -> dict:
    for section in NAV_SECTIONS:
        if any(child_key == active for _, child_key, _ in section["children"]):
            return section
    if active == "registry":
        return NAV_SECTIONS[0]
    return NAV_SECTIONS[0]


def _icon(path_d: str, cls: str = "w-5 h-5") -> str:
    return f'<svg class="{cls}" fill="none" viewBox="0 0 24 24" stroke-width="1.7" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="{escape(path_d)}"/></svg>'


def sidebar(active: str, built_at: str) -> str:
    active_section = _active_section(active)
    section_links = ""
    for section in NAV_SECTIONS:
        is_active = section["key"] == active_section["key"]
        active_cls = "bg-blue-50 text-blue-700 border-blue-200" if is_active else "text-gray-700 border-transparent hover:bg-gray-50 hover:border-gray-200"
        icon_cls = "w-5 h-5 " + ("text-blue-600" if is_active else "text-gray-400")
        section_links += (
            f'<a href="{section["href"]}" class="block rounded-xl border px-3 py-3 {active_cls} transition-colors">'
            '<div class="flex items-center gap-3">'
            f'<svg class="{icon_cls}" fill="none" viewBox="0 0 24 24" stroke-width="1.7" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="{escape(section["icon"])}"/></svg>'
            f'<div><div class="text-sm font-semibold">{escape(section["label"])}</div>'
            f'<div class="text-[11px] opacity-70">{escape(section["hint"])}</div></div>'
            '</div></a>'
        )

    child_links = ""
    for href, key, label in active_section["children"]:
        is_active = active == key
        cls = "bg-blue-600 text-white" if is_active else "bg-white text-gray-700 border border-gray-200 hover:border-blue-200 hover:text-blue-700"
        child_links += f'<a href="{href}" class="inline-flex items-center rounded-full px-3 py-1.5 text-xs font-medium {cls}">{escape(label)}</a>'

    mobile_links = "".join(
        f'<a href="{section["href"]}" class="px-3 py-1.5 rounded-full text-xs font-medium {"bg-blue-50 text-blue-700" if section["key"] == active_section["key"] else "bg-white text-gray-600 border border-gray-200"}">{escape(section["label"])}</a>'
        for section in NAV_SECTIONS
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
<aside class="fixed inset-y-0 left-0 w-72 bg-white border-r border-gray-200 flex flex-col z-30 hidden md:flex">
  <div class="px-5 py-4 border-b border-gray-100">
    <div class="flex items-center gap-3">
      <div class="w-9 h-9 rounded-lg bg-blue-600 text-white text-sm font-bold flex items-center justify-center">QG</div>
      <div>
        <div class="text-sm font-bold text-gray-900">OA QG</div>
        <div class="text-xs text-gray-400">{VERSION} · {escape(DOMAIN)}</div>
      </div>
    </div>
    <div class="mt-3 rounded-lg bg-slate-50 border border-slate-100 px-3 py-2 text-xs text-slate-600">
      Menu court: 5 sections. Les anciennes routes restent accessibles comme sous-pages de la section active.
    </div>
  </div>
  <nav class="px-3 py-3 space-y-2">{section_links}</nav>
  <div class="px-5 py-3 border-t border-gray-100">
    <div class="text-[11px] font-semibold uppercase tracking-wide text-gray-400 mb-2">Sous-pages · {escape(active_section["label"])}</div>
    <div class="flex flex-wrap gap-2">{child_links}</div>
  </div>
  <div class="mt-auto px-5 py-3 border-t border-gray-100">
    <div class="text-xs text-gray-400">Rebuild {escape(ts_short)} · <span title="dernier commit poussé">push {escape(last_push)}</span></div>
    <a href="/api/core-repos.json" class="text-xs text-blue-500 hover:underline">API JSON</a>
  </div>
</aside>
<div class="md:hidden bg-white border-b border-gray-200 px-4 py-3 sticky top-0 z-20">
  <div class="flex items-center gap-3 mb-2">
    <div class="w-8 h-8 rounded bg-blue-600 text-white text-xs font-bold flex items-center justify-center">QG</div>
    <div class="text-sm font-bold text-gray-900">OA QG</div>
  </div>
  <nav class="flex gap-2 overflow-x-auto pb-1">{mobile_links}</nav>
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
<main class="md:ml-72 min-h-screen">
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


def qg_delivery_focus(builds: dict, pending_alex_actions: int) -> str:
    """mandat:h-omar-night-2026-06-14 — bloc cockpit résultat/mandats.

    Compteur canonique: collect_blocages.py / var/blocages.json.
    Ne recompte pas directement var/decisions.json ici.
    """
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
        '<a href="/blocages/" class="block bg-white rounded-xl border border-amber-100 px-4 py-3 hover:border-amber-300 hover:shadow-sm transition">'
        '<div class="text-xs font-semibold uppercase tracking-wide text-amber-600">Blocages / mandats</div>'
        f'<div class="mt-1 text-sm font-semibold text-gray-900">{pending_alex_actions} action(s) Alex dans le compteur blocages</div>'
        '<div class="mt-1 text-xs text-gray-500">Source unique: collect_blocages.py · mandat:h-omar-night-2026-06-14 · décisions tracées en decision:* quand elles bloquent.</div>'
        '<div class="mt-2 text-xs text-amber-600">Voir blocages →</div></a>'
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



DOCS_ALLOWED_DIRS = (ROOT / "docs" / "plans", ROOT / "docs" / "references", ROOT / "docs" / "reviews")


def _doc_slug(path: Path) -> str:
    rel = path.relative_to(ROOT / "docs")
    return rel.as_posix().replace("/", "__")


def collect_public_docs(tmp: Path) -> list[dict]:
    # Expose une selection de Markdown sous /docs/ sans secrets.
    docs: list[dict] = []
    files_dir = tmp / "docs" / "files"
    files_dir.mkdir(parents=True, exist_ok=True)
    for base in DOCS_ALLOWED_DIRS:
        if not base.exists():
            continue
        for path in sorted(base.glob("*.md")):
            rel = path.relative_to(ROOT)
            slug = _doc_slug(path)
            text = path.read_text(encoding="utf-8", errors="replace")
            (files_dir / slug).write_text(text, encoding="utf-8")
            first_heading = next((line.lstrip("# ").strip() for line in text.splitlines() if line.startswith("#")), "")
            docs.append({
                "slug": slug,
                "title": first_heading or path.stem.replace("-", " "),
                "path": rel.as_posix(),
                "url": f"/docs/?doc={urllib.parse.quote(slug)}",
                "raw_url": f"/docs/files/{urllib.parse.quote(slug)}",
                "kind": rel.parts[1] if len(rel.parts) > 1 else "docs",
                "size": path.stat().st_size,
            })
    (tmp / "api" / "docs-index.json").write_text(
        json.dumps({"schema": "oa.docs-index/1", "items": docs}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return docs


def page_docs(docs: list[dict]) -> str:
    items = "".join(
        '<a class="block rounded-xl border border-slate-200 bg-white px-4 py-3 hover:border-blue-300 hover:shadow-sm transition" '
        f'href="{escape(doc["url"])}">'
        f'<div class="text-xs font-semibold uppercase tracking-wide text-blue-600">{escape(doc.get("kind", "docs"))}</div>'
        f'<div class="mt-1 text-sm font-semibold text-slate-900">{escape(doc.get("title", "Document"))}</div>'
        f'<div class="mt-1 text-xs font-mono text-slate-500">{escape(doc.get("path", ""))}</div>'
        '</a>'
        for doc in docs
    ) or '<div class="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">Aucun document expose.</div>'
    docs_json = json.dumps(docs, ensure_ascii=False).replace("</", "<\\/")
    return f'''
<section class="mb-6">
  <div class="flex flex-col gap-3 md:flex-row md:items-end md:justify-between">
    <div>
      <div class="text-xs font-semibold uppercase tracking-wide text-blue-600">Docs QG</div>
      <h1 class="text-2xl font-bold text-slate-950">Documents vérifiables</h1>
      <p class="mt-1 text-sm text-slate-500">Liens directs lisibles pour décisions, blocages, plans et références. Source exposée: <span class="font-mono">docs/plans</span> + <span class="font-mono">docs/references</span>.</p>
    </div>
    <a class="inline-flex items-center rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs font-medium text-slate-700 hover:border-blue-300" href="/api/docs-index.json">Index JSON</a>
  </div>
</section>
<section class="grid grid-cols-1 lg:grid-cols-[320px_1fr] gap-4">
  <aside class="space-y-2">{items}</aside>
  <article class="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm min-h-[60vh]">
    <div id="doc-meta" class="mb-4 text-xs text-slate-500">Sélectionne un document à gauche, ou utilise <span class="font-mono">?doc=&lt;slug&gt;</span>.</div>
    <div id="doc-view" class="max-w-none text-sm leading-7"><p class="text-slate-500">Aucun document sélectionné.</p></div>
  </article>
</section>
<script type="application/json" id="docs-index">{docs_json}</script>
<script>
const docs = JSON.parse(document.getElementById("docs-index").textContent);
const params = new URLSearchParams(window.location.search);
const requested = params.get("doc") || (docs[0] && docs[0].slug);
const doc = docs.find(d => d.slug === requested);
const entityMap = {{"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}};
function esc(s) {{ return String(s).replace(/[&<>\"']/g, c => entityMap[c]); }}
function inlineMd(s) {{
  return esc(s)
    .replace(/`([^`]+)`/g, "<code class='rounded bg-slate-100 px-1 py-0.5'>$1</code>")
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .replace(/\[([^\]]+)\]\((https?:[^)]+)\)/g, "<a class='text-blue-600 hover:underline' href='$2' target='_blank' rel='noreferrer'>$1</a>");
}}
function render(md) {{
  const out = [];
  let inCode = false, code = [];
  for (const line of md.split(/\r?\n/)) {{
    if (line.startsWith("```")) {{
      if (inCode) {{ out.push("<pre class='overflow-auto rounded-xl bg-slate-950 p-4 text-slate-100'><code>"+esc(code.join("\n"))+"</code></pre>"); code=[]; inCode=false; }}
      else inCode = true;
      continue;
    }}
    if (inCode) {{ code.push(line); continue; }}
    if (/^###\s+/.test(line)) out.push("<h3 class='mt-6 text-lg font-bold text-slate-900'>"+inlineMd(line.replace(/^###\s+/,""))+"</h3>");
    else if (/^##\s+/.test(line)) out.push("<h2 class='mt-8 border-t border-slate-100 pt-5 text-xl font-bold text-slate-950'>"+inlineMd(line.replace(/^##\s+/,""))+"</h2>");
    else if (/^#\s+/.test(line)) out.push("<h1 class='mb-4 text-2xl font-bold text-slate-950'>"+inlineMd(line.replace(/^#\s+/,""))+"</h1>");
    else if (/^[-*]\s+/.test(line)) out.push("<div class='my-1 pl-4 text-slate-700'>• "+inlineMd(line.replace(/^[-*]\s+/,""))+"</div>");
    else if (/^>\s?/.test(line)) out.push("<blockquote class='my-3 border-l-4 border-blue-200 bg-blue-50 px-4 py-2 text-slate-700'>"+inlineMd(line.replace(/^>\s?/,""))+"</blockquote>");
    else if (line.trim()==="") out.push("<div class='h-3'></div>");
    else out.push("<p class='my-2 text-slate-700'>"+inlineMd(line)+"</p>");
  }}
  return out.join("\n");
}}
if (doc) {{
  document.getElementById("doc-meta").innerHTML = "<span class='font-semibold text-slate-700'>"+esc(doc.title)+"</span><br><span class='font-mono'>"+esc(doc.path)+"</span> · <a class='text-blue-600 hover:underline' href='"+esc(doc.raw_url)+"'>raw</a>";
  fetch(doc.raw_url).then(r => r.text()).then(md => {{ document.getElementById("doc-view").innerHTML = render(md); }});
}}
</script>
'''
def page_registry(data: dict, pending_alex_actions: int = 0, builds_today: int = 0, objectifs: list | None = None, builds: dict | None = None, agent_loop_audit: dict | None = None, blocages: dict | None = None, vps_fleet: dict | None = None, agent_activity: dict | None = None) -> str:
    items = data["items"]
    counts = data["counts"]
    objectifs = objectifs or []
    builds = builds or {"days": []}
    audit_summary = (agent_loop_audit or {}).get("summary", {}) or {}
    total_orphans = int(audit_summary.get("total_orphans") or 0)

    # Tuile flotte VPS (rescue J4) : x/y rapportent + standards FAIL, détail sur /ops/.
    fleet_summary = (vps_fleet or {}).get("summary", {}) or {}
    fleet_reporting = int(fleet_summary.get("reporting") or 0)
    fleet_expected = int(fleet_summary.get("expected") or 0)
    fleet_fail = int(fleet_summary.get("standards_fail") or 0)
    fleet_accent = "text-red-600" if fleet_fail or fleet_reporting < fleet_expected else "text-gray-900"
    fleet_tile = (
        f'<a href="/ops/" class="block bg-white rounded-xl border border-gray-200 px-4 py-3 hover:border-blue-300 hover:shadow-sm transition">'
        f'<div class="flex items-center justify-between"><div><div class="text-2xl font-bold {fleet_accent}">{fleet_reporting}<span class="text-gray-400 text-sm font-normal">/{fleet_expected}</span></div>'
        f'<div class="text-xs text-gray-500 mt-0.5">VPS rapportent · {fleet_fail} standard(s) FAIL</div></div>'
        f'<span class="text-xs text-blue-500">Voir /ops/ →</span></div></a>'
    ) if fleet_expected else ""

    # Tuile activité agents : cockpit dynamique filtrable depuis Kanban + registry.
    activity_summary = (agent_activity or {}).get("summary", {}) or {}
    active_agents = int(activity_summary.get("agents") or 0)
    active_work = int(activity_summary.get("active") or 0)
    blocked_work = int(activity_summary.get("blocked") or 0)
    activity_accent = "text-red-600" if blocked_work else "text-gray-900"
    activity_tile = (
        f'<a href="/agent-activity/" class="block bg-white rounded-xl border border-gray-200 px-4 py-3 hover:border-blue-300 hover:shadow-sm transition">'
        f'<div class="flex items-center justify-between"><div><div class="text-2xl font-bold {activity_accent}">{active_work}<span class="text-gray-400 text-sm font-normal">/{active_agents}</span></div>'
        f'<div class="text-xs text-gray-500 mt-0.5">Activité agents · {blocked_work} bloquée(s) · filtres VPS/type/date</div></div>'
        f'<span class="text-xs text-blue-500">Voir agents →</span></div></a>'
    )

    # Tuiles d'action : blocages à trancher + builds du jour (liens dédiés).
    # Source unique du compteur Alex: collect_blocages.py (plus de recomptage décisions ici).
    tile_count = 4 + (1 if fleet_tile else 0)
    dec_accent = "text-amber-600" if pending_alex_actions else "text-gray-900"
    tiles = (
        f'<div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-{tile_count} gap-3 mb-3">'
        f'<a href="/blocages/" class="block bg-white rounded-xl border border-gray-200 px-4 py-3 hover:border-blue-300 hover:shadow-sm transition">'
        f'<div class="flex items-center justify-between"><div><div class="text-2xl font-bold {dec_accent}">{pending_alex_actions}</div>'
        f'<div class="text-xs text-gray-500 mt-0.5">Actions Alex à débloquer</div></div>'
        f'<span class="text-xs text-blue-500">Voir blocages →</span></div></a>'
        f'<a href="/builds/" class="block bg-white rounded-xl border border-gray-200 px-4 py-3 hover:border-blue-300 hover:shadow-sm transition">'
        f'<div class="flex items-center justify-between"><div><div class="text-2xl font-bold text-gray-900">{builds_today}</div>'
        f'<div class="text-xs text-gray-500 mt-0.5">Builds aujourd’hui</div></div>'
        f'<span class="text-xs text-blue-500">Voir →</span></div></a>'
        + activity_tile +
        f'<a href="/agent-loop/" class="block bg-white rounded-xl border border-gray-200 px-4 py-3 hover:border-blue-300 hover:shadow-sm transition">'
        f'<div class="flex items-center justify-between"><div><div class="text-2xl font-bold {"text-red-600" if total_orphans else "text-gray-900"}">{total_orphans}</div>'
        f'<div class="text-xs text-gray-500 mt-0.5">Orphelins Issue↔Kanban↔PR↔Gate · figé depuis 15/06 si non recronifié</div></div>'
        f'<span class="text-xs text-blue-500">Auditer →</span></div></a>'
        + fleet_tile +
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
    return qg_blocages_banner(blocages) + objectifs_summary(objectifs) + header + qg_delivery_focus(builds, pending_alex_actions) + tiles + stats + rows


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

    issues_value = escape(str(gh.get("open_issues") if gh.get("open_issues") is not None else "—"))
    prs_value = escape(str(gh.get("open_prs") if gh.get("open_prs") is not None else "—"))
    if repo:
        issues_metric = (
            f'<a href="https://github.com/{escape(repo)}/issues/" class="block bg-white rounded-xl border border-gray-200 px-4 py-3 hover:border-blue-300 hover:shadow-sm transition">'
            f'<div class="text-xs text-gray-500">Issues ouvertes</div><div class="text-2xl font-bold text-gray-900">{issues_value}</div></a>'
        )
        prs_metric = (
            f'<a href="https://github.com/{escape(repo)}/pulls/" class="block bg-white rounded-xl border border-gray-200 px-4 py-3 hover:border-blue-300 hover:shadow-sm transition">'
            f'<div class="text-xs text-gray-500">PRs ouvertes</div><div class="text-2xl font-bold text-gray-900">{prs_value}</div></a>'
        )
    else:
        issues_metric = f'<div class="bg-white rounded-xl border border-gray-200 px-4 py-3"><div class="text-xs text-gray-500">Issues ouvertes</div><div class="text-2xl font-bold text-gray-900">{issues_value}</div></div>'
        prs_metric = f'<div class="bg-white rounded-xl border border-gray-200 px-4 py-3"><div class="text-xs text-gray-500">PRs ouvertes</div><div class="text-2xl font-bold text-gray-900">{prs_value}</div></div>'

    html += '<div class="grid md:grid-cols-3 gap-4 mb-6">'
    html += issues_metric
    html += prs_metric
    html += f'<div class="bg-white rounded-xl border border-gray-200 px-4 py-3"><div class="text-xs text-gray-500">Head local</div><div class="text-sm font-mono text-gray-700 break-words mt-1">{escape(git.get("head") or "—")}</div></div>'
    html += '</div>'

    if app.get("id") == "app":
        html += appomar_resource_onboarding_spec(data.get("resource_onboarding") or {})

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
        "vault_unavailable": ("bg-amber-50 text-amber-700 border border-amber-200", "Vault indisponible"),
        "api_error":   ("bg-red-50 text-red-700 border border-red-200",         "Erreur Vault/API"),
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


def _fmt_int(value) -> str:
    try:
        return f"{int(value):,}".replace(",", " ")
    except Exception:
        return "—"


def _resource_onboarding_summary(payload: dict) -> dict:
    canonical = payload.get("canonical_cloud_index") or {}
    permissions = payload.get("default_permissions") or {}
    onboarding = payload.get("onboarding_step") or {}
    exclusions = payload.get("hard_exclusions") or []
    return {
        "schema": str(payload.get("resource_scope_schema") or "oa.resource-scope/v1"),
        "generated_at": str(payload.get("generated_at") or "unknown"),
        "status": str(payload.get("status") or "unknown"),
        "total_records": canonical.get("total_unique_records"),
        "google_records": canonical.get("google_drive_api_full_records"),
        "onedrive_records": canonical.get("onedrive_rclone_targeted_records"),
        "metadata_only": bool(canonical.get("metadata_only", True)),
        "text_extraction_status": str(canonical.get("text_extraction_status") or "planned_v3_controlled"),
        "permissions": permissions,
        "onboarding_steps": onboarding.get("steps") or [],
        "exclusions_count": len(exclusions) if isinstance(exclusions, list) else 0,
        # Security gate: QG public surface must not expose source names/subsets.
        # Keep only aggregate counts/status; full contract stays internal under var/.
        "v3_priority_count": len(payload.get("v3_text_extraction_priority") or []) if isinstance(payload.get("v3_text_extraction_priority"), list) else 0,
    }


def sanitize_resource_onboarding_public(payload: dict) -> dict:
    """Return the public/QG-safe resource onboarding snapshot.

    The internal contract may contain absolute local paths and source labels. Athena
    gate t_cb7a0754 requires public/api and /clients/ to expose counters/statuses
    only: no local paths, no source names, no raw file/document labels.
    """
    if not isinstance(payload, dict) or not payload:
        return {}
    summary = _resource_onboarding_summary(payload)
    permissions = summary.get("permissions") if isinstance(summary.get("permissions"), dict) else {}
    steps = summary.get("onboarding_steps") if isinstance(summary.get("onboarding_steps"), list) else []
    return {
        "schema": "oa.resource-onboarding/public.v0",
        "generated_at": summary.get("generated_at"),
        "status": summary.get("status"),
        "resource_scope_schema": summary.get("schema"),
        "visibility": "public_qg_redacted_counters_only",
        "canonical_cloud_index": {
            "total_unique_records": summary.get("total_records"),
            "google_drive_api_full_records": summary.get("google_records"),
            "onedrive_rclone_targeted_records": summary.get("onedrive_records"),
            "metadata_only": summary.get("metadata_only"),
            "text_extraction_status": summary.get("text_extraction_status"),
        },
        "onboarding_step": {
            "name": "Ressources & connaissances",
            "position_after": "Connexions",
            "steps": steps,
        },
        "default_permissions": permissions,
        "redaction": {
            "absolute_paths": "removed",
            "source_names": "removed",
            "file_names": "never_published",
            "raw_content": "never_published",
            "v3_priority_sources_count": summary.get("v3_priority_count"),
            "hard_exclusions_count": summary.get("exclusions_count"),
        },
    }


def redact_public_api_payload(value):
    """Recursively redact local filesystem paths from public JSON payloads."""
    if isinstance(value, dict):
        return {k: redact_public_api_payload(v) for k, v in value.items()}
    if isinstance(value, list):
        return [redact_public_api_payload(v) for v in value]
    if isinstance(value, str):
        value = re.sub(r"/home/omar/[^\"'\\s<>]+", "[redacted-path]", value)
        value = re.sub(r"/var/[^\"'\\s<>]+", "[redacted-path]", value)
        return value
    return value


def _resource_metric_card(label: str, value: str, sub: str) -> str:
    return (
        '<div class="rounded-lg bg-gray-50 border border-gray-100 px-3 py-2">'
        f'<div class="text-lg font-bold text-gray-900">{escape(value)}</div>'
        f'<div class="text-xs font-semibold text-gray-600">{escape(label)}</div>'
        f'<div class="text-xs text-gray-400 mt-1">{escape(sub)}</div>'
        '</div>'
    )


def qg_resource_onboarding_section(payload: dict) -> str:
    if not isinstance(payload, dict) or not payload:
        return (
            '<section class="bg-amber-50 border border-amber-200 rounded-xl px-5 py-4 mb-8 text-sm text-amber-800">'
            'Onboarding ressources documentaires absent — publier <span class="font-mono">vps-resource-onboarding-v0.json</span>.'
            '</section>'
        )
    summary = _resource_onboarding_summary(payload)
    permissions = summary["permissions"] if isinstance(summary["permissions"], dict) else {}
    permission_rows = [
        ("read_metadata", "lecture metadata"),
        ("read_text", "lecture texte"),
        ("write_new", "écriture nouvelle"),
        ("update_existing", "modification"),
        ("organize_suggest", "classement suggéré"),
        ("organize_apply", "classement appliqué"),
        ("delete", "suppression"),
    ]
    perms_html = "".join(
        '<div class="flex items-center justify-between gap-2 py-1 border-t border-gray-50 first:border-0">'
        f'<span>{escape(label)}</span><span class="font-mono text-gray-500 text-[11px]">{escape(str(permissions.get(key, "—")))}</span></div>'
        for key, label in permission_rows
    )
    v3_count = int(summary.get("v3_priority_count") or 0)
    v3_html = f'<span class="rounded bg-blue-50 text-blue-700 px-2 py-0.5 text-xs">{escape(str(v3_count))} lots candidats redacted</span>'
    steps = [str(x).replace("_", " ") for x in (summary.get("onboarding_steps") or [])][:7]
    steps_html = "".join(f'<li>{escape(step)}</li>' for step in steps)
    return (
        '<section class="bg-white rounded-xl border border-gray-200 overflow-hidden mb-8">'
        '<div class="px-4 py-3 border-b border-gray-100 flex items-center justify-between gap-3">'
        '<div><h2 class="text-sm font-bold text-gray-900">Ressources &amp; connaissances — onboarding VPS/client</h2>'
        f'<p class="text-xs text-gray-500">Vue gouvernance metadata-only · modèle <span class="font-mono">{escape(summary["schema"])}</span> · aucun nom de fichier ni contenu brut.</p></div>'
        '<a href="/api/vps-resource-onboarding-v0.json" class="text-xs text-blue-500 hover:underline">API onboarding</a>'
        '</div>'
        '<div class="grid md:grid-cols-4 gap-3 px-4 py-3 bg-gray-50">'
        f'{_resource_metric_card("Cloud Index records", _fmt_int(summary.get("total_records")), "records uniques metadata")}'
        f'{_resource_metric_card("Google Drive API full", _fmt_int(summary.get("google_records")), "crawl API complet, lecture seule")}'
        f'{_resource_metric_card("OneDrive ciblé", _fmt_int(summary.get("onedrive_records")), "rclone ciblé V2 conservé")}'
        f'{_resource_metric_card("V3 extraction contrôlée", "0 lancé", summary.get("text_extraction_status") or "planned")}'
        '</div>'
        '<div class="grid lg:grid-cols-3 gap-4 p-4">'
        '<article class="rounded-xl border border-gray-100 px-4 py-3 bg-white"><h3 class="text-xs font-bold uppercase tracking-wide text-gray-500 mb-2">Permissions agents</h3>'
        f'<div class="text-xs text-gray-600">{perms_html}</div></article>'
        '<article class="rounded-xl border border-gray-100 px-4 py-3 bg-white"><h3 class="text-xs font-bold uppercase tracking-wide text-gray-500 mb-2">Étape AppOmar</h3>'
        f'<ol class="list-decimal pl-4 text-xs text-gray-600 space-y-1">{steps_html}</ol></article>'
        '<article class="rounded-xl border border-gray-100 px-4 py-3 bg-white"><h3 class="text-xs font-bold uppercase tracking-wide text-gray-500 mb-2">Exclusions &amp; suivi</h3>'
        f'<div class="text-sm font-semibold text-gray-900">{escape(str(summary.get("exclusions_count")))} familles exclues par défaut</div>'
        '<div class="text-xs text-gray-500 mt-1">secrets, personnel, médical, corbeille, caches/builds/vendor restent hors surface.</div>'
        f'<div class="flex flex-wrap gap-1.5 mt-3">{v3_html}</div></article>'
        '</div></section>'
    )


def appomar_resource_onboarding_spec(payload: dict) -> str:
    if not isinstance(payload, dict) or not payload:
        return ""
    summary = _resource_onboarding_summary(payload)
    steps = [
        ("1", "Sources", "Google Drive, OneDrive, PC local, GitHub, dossiers VPS — connexion explicite, pas tout par défaut."),
        ("2", "Périmètres", "Choisir familles/dossiers autorisés; index_mode metadata_only ou text_extract_controlled."),
        ("3", "Classification", "business_admin, clients, sales_marketing, operations, knowledge_base, finance_legal, team_hr, personal_excluded."),
        ("4", "Permissions agents", "read_metadata, read_text contrôlé, write_new en zone autorisée, organize_suggest séparé de organize_apply."),
        ("5", "Exclusions", "Secrets, personnel/famille, médical, banque/crypto, corbeille, caches/builds/vendor."),
        ("6", "Boucle QG", "Résumé publié dans QG + prochaine action; extraction V3 uniquement par lot autorisé."),
    ]
    cards = "".join(
        '<div class="rounded-lg border border-gray-100 bg-gray-50 px-3 py-2">'
        f'<div class="flex items-center gap-2 mb-1"><span class="w-5 h-5 rounded-full bg-gray-900 text-white text-[11px] font-bold flex items-center justify-center">{n}</span><span class="text-sm font-semibold text-gray-900">{escape(title)}</span></div>'
        f'<div class="text-xs text-gray-600 leading-relaxed">{escape(text)}</div></div>'
        for n, title, text in steps
    )
    return (
        '<section class="bg-white rounded-xl border border-gray-200 overflow-hidden mb-6">'
        '<div class="px-4 py-3 border-b border-gray-100 flex items-center justify-between gap-3">'
        '<div><h2 class="text-sm font-bold text-gray-900">Spec onboarding AppOmar · Ressources &amp; connaissances</h2>'
        f'<p class="text-xs text-gray-500">Première UI/spec statique après Connexions · objet cible <span class="font-mono">{escape(summary["schema"])}</span>.</p></div>'
        '<a href="/api/vps-resource-onboarding-v0.json" class="text-xs text-blue-500 hover:underline">contrat JSON</a>'
        '</div>'
        '<div class="grid md:grid-cols-2 lg:grid-cols-3 gap-3 p-4">'
        f'{cards}'
        '</div>'
        '<div class="px-4 py-3 bg-blue-50 border-t border-blue-100 text-xs text-blue-800">'
        'Garde-fou V0: UI de choix et gouvernance seulement — aucune extraction texte V3, aucun renommage/déplacement, aucun contenu brut exposé.'
        '</div></section>'
    )


def page_clients(data: dict) -> str:
    fleet = data.get("fleet", [])
    html = (
        '<div class="flex items-center justify-between mb-6">'
        '<div><h1 class="text-xl font-bold text-gray-900">Clients — inventaire apps silencieux</h1>'
        '<p class="text-sm text-gray-500 mt-0.5">Inventaire applicatif redacted. La supervision, les dérives et la maturité VPS vivent uniquement dans <a href="/ops/" class="text-blue-600 hover:underline">/ops/</a>.</p></div>'
        '</div>'
    )
    html += (
        '<div class="bg-blue-50 border border-blue-100 rounded-xl px-4 py-3 text-sm text-blue-800 mb-6">'
        '<span class="font-semibold">Source de supervision unique :</span> <a href="/ops/" class="font-semibold underline">/ops/</a>. '
        'Cette page ne sert qu’à l’inventaire silencieux des apps par client/VPS; les matériaux V0 sont conservés comme compat legacy et renvoient vers /ops/.'
        '</div>'
    )
    html += qg_resource_onboarding_section(data.get("resource_onboarding") or {})

    app_inventory = data.get("vps_app_inventory") or {}
    inventory_nodes = app_inventory.get("nodes") or []
    if inventory_nodes:
        totals = app_inventory.get("totals") or {}
        html += '<section class="bg-white rounded-xl border border-gray-200 overflow-hidden mb-8">'
        html += '<div class="px-4 py-3 border-b border-gray-100 flex items-center justify-between gap-3">'
        html += '<div><h2 class="text-sm font-bold text-gray-900">Inventaire apps/version par VPS — silencieux</h2><p class="text-xs text-gray-500">Source: rapports <span class="font-mono">oa.vps-report/v1</span> · redacted · aucun log brut · pas de cockpit supervision ici.</p></div>'
        html += '<div class="flex gap-3"><a href="/api/vps-app-inventory.json" class="text-xs text-blue-500 hover:underline">API inventory</a><a href="/ops/" class="text-xs text-blue-500 hover:underline">Supervision unique /ops/</a></div>'
        html += '</div>'
        html += '<div class="grid grid-cols-2 lg:grid-cols-6 gap-3 px-4 py-3 bg-gray-50">'
        html += f'<div><div class="text-lg font-bold text-gray-900">{escape(str(totals.get("canonical_nodes", totals.get("nodes", 0))))}</div><div class="text-xs text-gray-500">VPS canoniques</div></div>'
        html += f'<div><div class="text-lg font-bold text-gray-900">{escape(str(totals.get("apps", 0)))}</div><div class="text-xs text-gray-500">apps suivies</div></div>'
        for st, label in [("pass", "PASS app"), ("fail", "FAIL app"), ("verdict_unknown", "UNKNOWN app"), ("standards_fail", "compat V0: FAIL standards")]:
            html += f'<div><div class="text-lg font-bold text-gray-900">{escape(str(totals.get(st, 0)))}</div><div class="text-xs text-gray-500">{label}</div></div>'
        html += '</div>'
        html += '<div class="divide-y divide-gray-100">'
        for node in inventory_nodes:
            summary = node.get("summary") or {}
            standards_summary = node.get("standards_summary") or {}
            apps = node.get("apps") or []
            standards_reported = node.get("standards") or []
            raw_node_label = str(node.get("node") or "unknown")
            alias_of = str(node.get("alias_of") or "")
            canonical_node = str(node.get("canonical_node") or raw_node_label)
            node_label = f"{raw_node_label} (alias {alias_of})" if alias_of else raw_node_label
            tenant = str(node.get("tenant") or "unknown")
            agent = str(node.get("agent") or "unknown")
            generated = str(node.get("generated_at") or "unknown")
            health = str(node.get("health_status") or "unknown")
            health_cls = "pill-ok" if health == "ok" else "pill-err" if health in {"blocked", "fail"} else "pill-warn" if health in {"degraded", "warning"} else "bg-gray-100 text-gray-600 border border-gray-200"
            html += '<div class="px-4 py-4">'
            html += '<div class="flex flex-wrap items-center justify-between gap-2 mb-3">'
            html += f'<div><div class="text-sm font-bold text-gray-900 uppercase">{escape(node_label)}</div><div class="text-xs text-gray-400">tenant {escape(tenant)} · agent {escape(agent)} · check {escape(generated)}</div></div>'
            html += f'<div class="flex items-center gap-2"><span class="{health_cls} rounded-full px-2 py-0.5 text-xs font-medium">{escape(health)}</span><span class="text-xs text-gray-500">{escape(str(summary.get("pass", 0)))} PASS app · {escape(str(summary.get("fail", 0)))} FAIL app · compat V0 standards: {escape(str(standards_summary.get("fail", 0)))} FAIL · détails <a href="/ops/" class="text-blue-500 hover:underline">/ops/</a></span></div>'
            html += '</div>'
            if alias_of:
                html += f'<div class="mb-3 rounded-lg border border-blue-100 bg-blue-50 px-3 py-2 text-xs text-blue-800">Alias explicite: <span class="font-mono">{escape(raw_node_label)}</span> est rattaché à <span class="font-mono">{escape(canonical_node)}</span>. Il reste visible ici pour compatibilité inventaire, mais ne crée pas un 4e VPS de supervision; voir <a href="/ops/" class="underline">/ops/</a>.</div>'
            html += '<div class="overflow-x-auto"><table class="min-w-full text-xs"><thead><tr class="text-left text-gray-400 uppercase"><th class="py-1 pr-3">App</th><th class="py-1 pr-3">Installée</th><th class="py-1 pr-3">Version</th><th class="py-1 pr-3">Attendue</th><th class="py-1 pr-3">Verdict</th><th class="py-1 pr-3">Statut brut</th><th class="py-1 pr-3">Preuve</th></tr></thead><tbody>'
            for app in apps:
                verdict = str(app.get("verdict") or "UNKNOWN")
                verdict_cls = "pill-ok" if verdict == "PASS" else "pill-err" if verdict == "FAIL" else "bg-gray-100 text-gray-600 border border-gray-200"
                installed = "oui" if app.get("installed") else "non"
                html += '<tr class="border-t border-gray-50">'
                html += f'<td class="py-1.5 pr-3 font-semibold text-gray-800">{escape(str(app.get("name") or app.get("app_id") or ""))}</td>'
                html += f'<td class="py-1.5 pr-3 text-gray-600">{installed}</td>'
                html += f'<td class="py-1.5 pr-3 font-mono text-gray-600">{escape(str(app.get("version_installed") or "unknown"))}</td>'
                html += f'<td class="py-1.5 pr-3 font-mono text-gray-500">{escape(str(app.get("version_expected") or "policy-current"))}</td>'
                html += f'<td class="py-1.5 pr-3"><span class="{verdict_cls} rounded-full px-2 py-0.5 font-medium">{escape(verdict)}</span></td>'
                html += f'<td class="py-1.5 pr-3 text-gray-500">{escape(str(app.get("raw_status") or app.get("status") or "unknown"))}</td>'
                html += f'<td class="py-1.5 pr-3 text-gray-400">{escape(str(app.get("source") or "report"))}</td>'
                html += '</tr>'
            html += '</tbody></table></div>'
            if standards_reported:
                html += '<div class="mt-4 rounded-lg border border-gray-100 bg-gray-50 px-3 py-2">'
                html += f'<div class="text-xs text-gray-600"><span class="font-bold text-gray-700">Compat legacy V0 — standards redacted conservés hors cockpit :</span> {escape(str(standards_summary.get("pass", 0)))} PASS · {escape(str(standards_summary.get("fail", 0)))} FAIL · {escape(str(standards_summary.get("unknown", 0)))} UNKNOWN. Source de supervision unique et détail actionnable : <a href="/ops/" class="text-blue-500 hover:underline">/ops/</a>.</div>'
                html += '</div>'
            html += '</div>'
        html += '</div></section>'
    else:
        html += '<div class="bg-amber-50 border border-amber-200 rounded-xl px-5 py-4 text-sm text-amber-800 mb-8">Inventaire apps/version absent — attendre un rapport <span class="font-mono">oa.vps-report/v1</span> avec <span class="font-mono">installed_apps</span>.</div>'

    return html


def _num(v) -> int:
    try:
        return int(v or 0)
    except Exception:
        return 0


def _vps_fleet_section(vps_fleet: dict | None) -> str:
    """Bloc « où j'en suis techniquement, sur chaque VPS » (demande Alex, rescue J4).

    Un bloc par VPS attendu : maturité en grand, liste INTÉGRALE des standards
    FAIL (item_id + preuve redacted, zéro ellipsis), compteur apps par kind,
    next_action ownerisée, horodatage. Rapport absent/stale = bloc ambre —
    c'est une alerte au sens de la doctrine H-Omar, pas une ligne discrète.
    """
    vps_fleet = vps_fleet if isinstance(vps_fleet, dict) else {}
    nodes = vps_fleet.get("nodes") or []
    if not nodes:
        return (
            '<div class="bg-amber-50 border border-amber-200 rounded-xl px-5 py-4 mb-6 text-sm text-amber-800">'
            'Flotte VPS : aucun rapport <span class="font-mono">oa.vps-report/v1</span> lisible dans l&#39;inbox inter-VPS.</div>'
        )
    s = vps_fleet.get("summary") or {}
    reporting = int(s.get("reporting") or 0)
    en_derive = int(s.get("en_derive") or 0)
    muets = int(s.get("muets") or 0)
    html = '<section class="bg-white rounded-xl border border-gray-200 overflow-hidden mb-6">'
    html += '<div class="px-4 py-3 border-b border-gray-100 flex items-center justify-between gap-3">'
    html += ('<div><h2 class="text-sm font-bold text-gray-900">Flotte VPS — où j&#39;en suis, machine par machine</h2>'
             '<p class="text-xs text-gray-500">Rapports <span class="font-mono">oa.vps-report/v1</span> · inbox inter-VPS · fraîcheur attendue &lt; 36 h · muet = alerte.</p></div>')
    html += '<a href="/api/ops/vps-fleet.json" class="text-xs text-blue-500 hover:underline">API flotte</a>'
    html += '</div>'
    derive_cls = "text-red-700" if en_derive else "text-green-700"
    muet_cls = "text-amber-700" if muets else "text-green-700"
    html += (
        '<div class="px-4 py-3 bg-gray-50 border-b border-gray-100 text-base font-bold text-gray-900">'
        f'{reporting} VPS rapportent · <span class="{derive_cls}">{en_derive} en dérive</span> · '
        f'<span class="{muet_cls}">{muets} muet(s)</span></div>'
    )
    for node in nodes:
        status = str(node.get("report_status") or "missing")
        label = str(node.get("label") or node.get("node") or "vps")
        vps_id = str(node.get("vps_id") or "")
        owner_transport = str(node.get("transport_owner") or "inconnu")
        if status == "missing":
            html += '<div class="px-4 py-4 border-b border-gray-100 last:border-0 bg-amber-50">'
            html += ('<div class="flex items-center justify-between gap-2 flex-wrap">'
                     f'<div class="text-sm font-bold text-gray-900 uppercase">{escape(vps_id)}</div>'
                     '<span class="pill-warn rounded-full px-2 py-0.5 text-xs font-medium">rapport attendu — jamais reçu</span></div>')
            html += f'<div class="text-xs text-gray-500 mt-0.5">{escape(label)}</div>'
            html += ('<div class="text-sm text-amber-800 mt-2">Aucun rapport <span class="font-mono">oa.vps-report/v1</span> '
                     'dans l&#39;inbox — VPS muet, alerte doctrine H-Omar.</div>')
            html += f'<div class="text-xs text-gray-600 mt-1">Outbox attendue : <span class="font-mono">{escape(str(node.get("expected_path") or "non définie"))}</span></div>'
            html += f'<div class="text-xs text-gray-600">Transport : owner <span class="font-semibold">{escape(owner_transport)}</span></div>'
            html += '</div>'
            continue
        stale = status == "stale"
        age_hours = node.get("age_hours")
        age_txt = f"{age_hours} h" if age_hours is not None else "âge inconnu"
        maturity = str(node.get("maturity") or "UNKNOWN")
        partial = bool(node.get("partial"))
        n_pass = int(node.get("standards_pass") or 0)
        n_fail = int(node.get("standards_fail") or 0)
        pct = node.get("standards_pass_pct")
        mat_cls = "text-red-700" if maturity == "FAIL" else "text-green-700" if maturity == "PASS" else "text-amber-700"
        row_cls = "bg-amber-50" if stale else ""
        html += f'<div class="px-4 py-4 border-b border-gray-100 last:border-0 {row_cls}">'
        pill = ('<span class="pill-warn rounded-full px-2 py-0.5 text-xs font-medium">stale depuis ' + escape(age_txt) + '</span>'
                if stale else '<span class="pill-ok rounded-full px-2 py-0.5 text-xs font-medium">rapport frais</span>')
        html += ('<div class="flex items-center justify-between gap-2 flex-wrap">'
                 f'<div class="text-sm font-bold text-gray-900 uppercase">{escape(vps_id)}</div>{pill}</div>')
        html += f'<div class="text-xs text-gray-500 mt-0.5">{escape(label)} · tenant {escape(str(node.get("tenant") or "unknown"))}</div>'
        if stale:
            html += ('<div class="text-sm text-amber-800 mt-2">Rapport attendu — stale depuis '
                     f'{escape(age_txt)} (seuil {VPS_REPORT_FRESH_HOURS} h) : alerte doctrine H-Omar. '
                     f'Outbox : <span class="font-mono">{escape(str(node.get("expected_path") or node.get("source_path") or ""))}</span> · '
                     f'transport owner <span class="font-semibold">{escape(owner_transport)}</span>.</div>')
        # Maturité en grand
        if partial:
            html += (f'<div class="mt-2 text-3xl font-bold {mat_cls}">maturité {escape(maturity)}</div>'
                     '<div class="text-xs text-amber-700 mt-0.5">rapport partiel — aucun <span class="font-mono">standards[]</span> fourni, maturité invérifiable.</div>')
        else:
            html += (f'<div class="mt-2 text-3xl font-bold {mat_cls}">{n_pass} PASS / {n_fail} FAIL'
                     + (f'<span class="text-lg font-semibold text-gray-500"> · {escape(str(pct))}%</span>' if pct is not None else '')
                     + '</div>')
            html += f'<div class="text-xs {mat_cls} mt-0.5 font-semibold">maturité {escape(maturity)}</div>'
        fails = node.get("fails") or []
        if fails:
            html += '<div class="mt-2 space-y-1">'
            for f_item in fails:
                html += ('<div class="text-sm text-gray-800"><span class="font-mono text-xs font-semibold text-red-700">'
                         f'{escape(str(f_item.get("item_id") or ""))}</span> — {escape(str(f_item.get("proof_redacted") or ""))}</div>')
            html += '</div>'
        kinds = node.get("apps_by_kind") or {}
        kinds_txt = " · ".join(f"{k} {v}" for k, v in kinds.items()) or "aucune app rapportée"
        html += f'<div class="text-xs text-gray-600 mt-2"><span class="font-semibold">{int(node.get("apps_total") or 0)} apps</span> : {escape(kinds_txt)}</div>'
        na = node.get("next_action") or {}
        html += (f'<div class="text-xs text-gray-700 mt-1">Next : {escape(str(na.get("action_1_line") or "non renseignée"))} '
                 f'— owner <span class="font-semibold">{escape(str(na.get("owner") or "unknown"))}</span></div>')
        html += f'<div class="text-xs text-gray-400 mt-1">généré {escape(str(node.get("generated_at") or "?"))} · il y a {escape(age_txt)} · source <span class="font-mono">{escape(str(node.get("source_path") or ""))}</span></div>'
        html += '</div>'
    html += ('<div class="px-4 py-3 bg-gray-50 text-xs text-gray-500">'
             'SAV : non instrumenté — aucun flux SAV n&#39;existe encore.</div>')
    html += '</section>'
    return html


def _hub_node_maturity_section(hub_node_maturity: dict | None) -> str:
    """Synthèse QG des rapports Hub node v1: source/fraîcheur/score/gaps, jamais logs locaux."""
    payload = hub_node_maturity if isinstance(hub_node_maturity, dict) else {}
    nodes = payload.get("nodes") or []
    summary = payload.get("summary") or {}
    html = '<section class="bg-white rounded-xl border border-gray-200 overflow-hidden mb-6">'
    html += '<div class="px-4 py-3 border-b border-gray-100 flex items-center justify-between gap-3">'
    html += ('<div><h2 class="text-sm font-bold text-gray-900">Maturité HubFleet — rapports Hub node v1</h2>'
             '<p class="text-xs text-gray-500">Source <span class="font-mono">oa.hub-node-report/v1</span> · QG synthèse uniquement · unknown si rapport absent.</p></div>')
    html += '<a href="/api/ops/hub-node-maturity.json" class="text-xs text-blue-500 hover:underline">API maturité</a>'
    html += '</div>'
    html += ('<div class="px-4 py-3 bg-gray-50 border-b border-gray-100 text-base font-bold text-gray-900">'
             f'{escape(str(summary.get("reporting", 0)))} / {escape(str(summary.get("expected", 0)))} rapports · '
             f'score moyen {escape(str(summary.get("avg_score") if summary.get("avg_score") is not None else "unknown"))} · '
             f'{escape(str(summary.get("priority_gaps", 0)))} gap(s) prioritaires</div>')
    if not nodes:
        html += '<div class="px-4 py-4 text-sm text-amber-800 bg-amber-50">Aucun rapport Hub node lisible — QG garde unknown.</div>'
        html += '</section>'
        return html
    html += '<div class="grid md:grid-cols-2 gap-3 p-4">'
    for node in nodes:
        status = str(node.get("status") or "unknown")
        report_status = str(node.get("report_status") or "missing")
        score = node.get("score")
        score_txt = str(score) if score is not None else "unknown"
        cls = "border-green-200 bg-green-50" if status == "ok" else "border-amber-200 bg-amber-50" if status in {"degraded", "unknown"} else "border-red-200 bg-red-50"
        status_cls = "text-green-700" if status == "ok" else "text-amber-700" if status in {"degraded", "unknown"} else "text-red-700"
        freshness = node.get("freshness") if isinstance(node.get("freshness"), dict) else {}
        source = node.get("source") if isinstance(node.get("source"), dict) else {}
        hermes = node.get("hermes_version") if isinstance(node.get("hermes_version"), dict) else {}
        gateway_raw = hermes.get("gateway_status")
        gateway = gateway_raw if isinstance(gateway_raw, dict) else {}
        gaps = node.get("priority_gaps") or []
        next_action = node.get("next_action") or {}
        html += f'<div class="rounded-xl border {cls} px-4 py-3">'
        html += '<div class="flex items-start justify-between gap-3">'
        html += f'<div><div class="text-sm font-bold text-gray-900">{escape(str(node.get("label") or node.get("node_id") or "node"))}</div>'
        html += f'<div class="text-xs text-gray-500 font-mono">{escape(str(node.get("node_id") or ""))} · {escape(str(node.get("kind") or "unknown"))}</div></div>'
        html += f'<div class="text-right"><div class="text-2xl font-bold {status_cls}">{escape(score_txt)}</div><div class="text-xs text-gray-500">{escape(str(node.get("level") or "unknown"))}</div></div>'
        html += '</div>'
        html += f'<div class="text-xs {status_cls} font-semibold mt-2">status {escape(status)} · rapport {escape(report_status)}</div>'
        html += f'<div class="text-xs text-gray-600 mt-1">Hermes {escape(str(hermes.get("current_version") or "unknown"))} · upstream {escape(str(hermes.get("upstream_status") or "unknown"))} · gateway {escape(str(gateway.get("status") or "unknown"))}</div>'
        html += f'<div class="text-xs text-gray-500 mt-1">fraîcheur {escape(str(freshness.get("status") or "unknown"))} · checked {escape(str(freshness.get("checked_at") or "unknown"))}</div>'
        if gaps:
            html += '<div class="mt-2 space-y-1">'
            for gap in gaps[:4]:
                html += f'<div class="text-xs text-gray-700"><span class="font-mono font-semibold">{escape(str(gap.get("domain") or "gap"))}</span> — {escape(str(gap.get("summary") or ""))}</div>'
            html += '</div>'
        else:
            html += '<div class="text-xs text-green-700 mt-2">Aucun gap prioritaire reporté.</div>'
        html += f'<div class="text-xs text-gray-700 mt-2">Next : {escape(str(next_action.get("label") or "unknown"))} — owner <span class="font-semibold">{escape(str(next_action.get("owner") or "unknown"))}</span></div>'
        html += f'<div class="text-[11px] text-gray-400 mt-2">source {escape(str(source.get("kind") or "unknown"))}/{escape(str(source.get("mode") or "unknown"))} · <span class="font-mono">{escape(str(node.get("source_path") or "absent"))}</span></div>'
        html += '</div>'
    html += '</div>'
    html += '<div class="px-4 py-3 bg-gray-50 text-xs text-gray-500">Garde-fou: QG ne duplique pas les logs locaux et ne centralise pas de secret; il affiche uniquement les résumés redacted Hub.</div>'
    html += '</section>'
    return html


def page_ops(ledger: dict, repo_health: dict | None = None, storage: dict | None = None, vps_fleet: dict | None = None, hub_node_maturity: dict | None = None) -> str:
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
    # EN TÊTE (demande Alex 07/07) : la flotte VPS — chaque machine, sa maturité.
    html += _hub_node_maturity_section(hub_node_maturity)
    html += _vps_fleet_section(vps_fleet)
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
        f'<p class="text-sm text-gray-500 mt-0.5">{len(objectifs)} objectif(s) — snapshot figé depuis le 14/06, relié aux décisions qui les débloquent.</p></div></div>'
        '<div class="bg-amber-50 border border-amber-200 rounded-xl px-4 py-3 mb-4 text-sm text-amber-800">Donnée figée depuis le 14/06 : page conservée pour lecture, pas présentée comme live.</div>'
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
    """Page 1 du QG — le manifeste en 1-2-3 lisible, zéro colonnes (refonte Alex 06/07).

    Source de vérité = docs 02/02bis/INDEX du dossier « Renew OA V2 - validated
    by Claude » (28/05/2026) + décision pricing 3f7d86e712 (tranchée 06/07).
    Structure numérotée pure, une seule largeur de colonne de texte, liens inline.
    Chaque section porte son statut honnête : validé 28/05 / tranché 06/07 /
    projection — pas de pourcentage inventé.
    """
    if not manifeste:
        return ('<h1 class="text-xl font-bold text-gray-900 mb-4">Manifeste</h1>'
                '<div class="bg-amber-50 border border-amber-200 rounded-xl px-5 py-4 text-sm text-amber-700">'
                'var/manifeste.json absent ou vide — le manifeste source reste '
                '<span class="font-mono">11-Pilotage/Renew OA V2 - validated by Claude/02-manifeste-business-interne.md</span>.</div>')

    offre = manifeste.get("offre") or {}
    footer = manifeste.get("footer") or {}
    lettres = ["A", "B", "C", "D", "E", "F"]

    badges = {
        "valide":     ("validé 28/05", "pill-ok"),
        "tranche":    ("tranché 06/07", "bg-blue-50 text-blue-700 border border-blue-200"),
        "projection": ("projection", "pill-warn"),
    }

    def badge(statut: str) -> str:
        label, cls = badges.get(statut, badges["projection"])
        return f'<span class="ml-2 inline-flex items-center rounded-full px-2 py-0.5 text-xs font-normal {cls}">{escape(label)}</span>'

    def section_titre(num: int, titre: str, statut: str) -> str:
        return (f'<h2 class="text-base font-bold text-gray-900 mt-8 mb-2 flex items-baseline flex-wrap">'
                f'<span>{num}. {escape(titre)}</span>{badge(statut)}</h2>')

    def sous_point(lettre: str, texte_html: str) -> str:
        return (f'<div class="flex gap-2 py-1 text-sm text-gray-700 leading-relaxed">'
                f'<span class="font-semibold text-gray-400 shrink-0 w-5">{lettre}.</span>'
                f'<span>{texte_html}</span></div>')

    def lien_inline(url: str, label: str | None = None) -> str:
        if not url:
            return '<span class="text-gray-400">pas encore live</span>'
        label = label or url.replace("https://", "").rstrip("/")
        return f'<a href="{escape(url)}" target="_blank" rel="noopener" class="text-blue-600 hover:underline">{escape(label)}</a>'

    # Statuts par section — le début du % de complétion demandé par Alex :
    # validé / tranché / projection, section par section, rien d'inventé.
    statuts = ["valide", "valide", "tranche", "projection", "valide"]
    n_valides = statuts.count("valide")
    n_tranches = statuts.count("tranche")
    n_projections = statuts.count("projection")
    indicateur = f"{n_valides} sections sur {len(statuts)} validées (28/05)"
    if n_tranches:
        indicateur += f" · {n_tranches} tranchée (06/07)"
    if n_projections:
        indicateur += f" · {n_projections} en projection"

    html = '<div class="max-w-3xl">'
    html += (
        '<div class="mb-2">'
        '<h1 class="text-xl font-bold text-gray-900">Manifeste — la boussole OA</h1>'
        f'<p class="text-sm text-gray-500 mt-0.5">{escape(indicateur)} — '
        'source <a href="/api/manifeste.json" class="text-blue-500 hover:underline">manifeste.json</a>, '
        'docs 02/02bis du dossier Renew OA V2.</p>'
        '</div>'
    )

    # ── 1. La promesse (2 phrases) ─────────────────────────────────────────────
    html += section_titre(1, "La promesse", statuts[0])
    html += (
        f'<p class="text-sm text-gray-800 leading-relaxed">« {escape(str(manifeste.get("promesse") or ""))} » '
        f'{escape(str(offre.get("profil") or ""))}</p>'
    )

    # ── 2. Le funnel (A-B-C-D, une ligne + lien + état) ───────────────────────
    html += section_titre(2, "Le funnel", statuts[1])
    for i, step in enumerate(manifeste.get("funnel", [])):
        nom = escape(str(step.get("nom") or ""))
        role = escape(str(step.get("role") or ""))
        horizon = escape(str(step.get("chantier_horizon") or "?"))
        rang = step.get("chantier_rang", "?")
        texte = (f'<span class="font-semibold text-gray-900">{nom}</span> — {role} '
                 f'{lien_inline(str(step.get("lien") or ""))} '
                 f'<span class="text-xs text-gray-400">({horizon} · rang {rang})</span>')
        html += sous_point(lettres[i], texte)
    html += ('<p class="text-xs text-gray-400 mt-1">Ordre de finition détaillé dans '
             '<a href="/chantiers/" class="text-blue-500 hover:underline">/chantiers/</a>.</p>')

    # ── 3. L'offre (3 lignes — pricing tranché 06/07) ─────────────────────────
    html += section_titre(3, "L'offre", statuts[2])
    pricing = str(offre.get("pricing_note") or "")
    if not pricing or "arbitrage" in pricing:
        # Filet : la décision 3f7d86e712 a tranché le 06/07 — même si le JSON
        # runtime n'a pas encore été mis à jour, la page dit la vérité du jour.
        pricing = ("Entrée à 67 EUR/mois — le reste est variable selon le devis et les modules retenus. "
                   "La grille par module sera définie avec la brique devis.")
    decision_lien = str(offre.get("pricing_decision_lien") or "/decisions/#card-3f7d86e712")
    cibles = [str(p).split("(")[0].strip() for p in offre.get("pour_qui", []) if p]
    pour_qui_ligne = " · ".join(cibles) if cibles else "cibles non renseignées (voir doc 02)"
    html += sous_point("A", '<span class="font-semibold text-gray-900">Pour qui</span> — '
                       + escape(pour_qui_ligne))
    html += sous_point("B", '<span class="font-semibold text-gray-900">Ce qu\'on livre</span> — '
                       + escape(str(offre.get("quoi") or "")))
    html += sous_point("C", '<span class="font-semibold text-gray-900">Le prix</span> — '
                       + escape(pricing) + " "
                       + f'<a href="{escape(decision_lien)}" class="text-blue-600 hover:underline">décision 3f7d86e712</a>')

    # ── 4. Les 4 socles (A-B-C-D, une ligne + lien) ───────────────────────────
    html += section_titre(4, "Les 4 socles", statuts[3])
    for i, socle in enumerate(manifeste.get("socles", [])):
        nom = escape(str(socle.get("nom") or ""))
        role = escape(str(socle.get("role") or ""))
        texte = (f'<span class="font-semibold text-gray-900">{nom}</span> — {role} '
                 f'{lien_inline(str(socle.get("lien") or ""))}')
        html += sous_point(lettres[i], texte)

    # ── 5. La règle (handbook-first, 1 phrase) ────────────────────────────────
    html += section_titre(5, "La règle", statuts[4])
    html += (
        f'<p class="text-sm text-gray-800 leading-relaxed">{escape(str(manifeste.get("regle") or ""))} '
        f'{escape(str(footer.get("handbook_first") or ""))}</p>'
    )

    # ── Sources (fichiers de vérité) ──────────────────────────────────────────
    html += '<div class="border-t border-gray-200 mt-8 pt-4">'
    html += f'<div class="text-xs text-gray-500 mb-1">{escape(str(footer.get("validation") or ""))}</div>'
    for s in manifeste.get("sources", []):
        html += (
            '<div class="text-xs py-0.5">'
            f'<span class="text-gray-500">{escape(str(s.get("label") or ""))}</span> '
            f'<span class="font-mono text-gray-400 break-all">{escape(str(s.get("path") or ""))}</span></div>'
        )
    html += '</div></div>'
    return html


_CARTE_CELL_CLS = {
    "vert":  "bg-green-100 border border-green-300 text-green-900 hover:border-green-500",
    "jaune": "bg-amber-100 border border-amber-300 text-amber-900 hover:border-amber-500",
    "rouge": "bg-red-100 border border-red-300 text-red-900 hover:border-red-500",
    "gris":  "bg-gray-100 border border-dashed border-gray-300 text-gray-500 hover:border-gray-400",
}

_CARTE_DOT_CLS = {
    "vert": "bg-green-500", "jaune": "bg-amber-400", "rouge": "bg-red-500", "gris": "bg-gray-300",
}


def page_carte(carte: dict) -> str:
    """La Carte — le puzzle OA, toutes les strates (vision Alex 07/07).

    Source unique : var/carte.json (collect_carte.py, republié en /api/carte.json).
    Une ligne par strate, une cellule par module, couleur TOUJOURS issue d'une
    source mesurée — le gris est une dette de mesure, jamais un acquis.
    """
    html = (
        '<div class="mb-6">'
        '<h1 class="text-xl font-bold text-gray-900">Carte — le puzzle OA, strate par strate</h1>'
        '<p class="text-sm text-gray-500 mt-0.5">Toutes les briques — produit, fonctionnel, technique, sécurité, data, agents — '
        'où on en est, ce qui est problématique, où on doit aller. '
        'Chaque couleur vient d\'une source mesurée — source <a href="/api/carte.json" class="text-blue-500 hover:underline">carte.json</a>.</p>'
        '</div>'
    )
    strates = carte.get("strates", []) if isinstance(carte, dict) else []
    if not strates:
        return html + '<div class="bg-amber-50 border border-amber-200 rounded-xl px-5 py-4 text-sm text-amber-700">Carte indisponible — var/carte.json absent ou vide (run scripts/collect_carte.py).</div>'

    g = carte.get("kpi_global", {}) or {}
    compteurs = g.get("compteurs", {}) or {}
    html += (
        '<div class="bg-white rounded-xl border border-gray-200 px-5 py-4 mb-4">'
        '<div class="text-xs font-semibold uppercase tracking-wide text-blue-600">KPI global — deux chiffres, l\'honnêteté du gris</div>'
        f'<div class="mt-1 text-lg font-bold text-gray-900">{escape(str(g.get("libelle") or ""))}</div>'
        f'<div class="mt-1 text-xs text-gray-500">{g.get("cellules", 0)} cellules · '
        f'{compteurs.get("vert", 0)} vert · {compteurs.get("jaune", 0)} jaune · {compteurs.get("rouge", 0)} rouge · '
        f'{compteurs.get("gris", 0)} gris (dette de mesure) · généré {escape(str(carte.get("generated_at") or ""))}</div>'
        '</div>'
    )

    regles = carte.get("regle_couleurs", {}) or {}
    html += '<div class="bg-white rounded-xl border border-gray-200 px-5 py-3 mb-6"><div class="text-xs font-semibold uppercase tracking-wide text-gray-500 mb-2">Légende — la règle des couleurs</div><div class="grid grid-cols-1 md:grid-cols-2 gap-x-6 gap-y-1">'
    for couleur in ("vert", "jaune", "rouge", "gris"):
        html += (
            f'<div class="flex items-start gap-2 text-xs text-gray-600">'
            f'<span class="mt-1 w-2.5 h-2.5 rounded-sm shrink-0 {_CARTE_DOT_CLS[couleur]}"></span>'
            f'<span><span class="font-semibold">{couleur}</span> = {escape(str(regles.get(couleur) or ""))}</span></div>'
        )
    html += '</div></div>'

    for strate in strates:
        kpi = strate.get("kpi", {}) or {}
        cpt = kpi.get("compteurs", {}) or {}
        html += (
            '<div class="bg-white rounded-xl border border-gray-200 px-5 py-4 mb-4">'
            '<div class="flex flex-wrap items-baseline justify-between gap-2 mb-3">'
            f'<div class="flex items-baseline gap-3"><h2 class="text-sm font-bold text-gray-900">{escape(str(strate.get("nom") or ""))}</h2>'
            f'<span class="text-sm font-semibold text-blue-700">{escape(str(kpi.get("valeur") or ""))}</span></div>'
            f'<div class="text-xs text-gray-400">{escape(str(kpi.get("label") or ""))} · cible : {escape(str(kpi.get("cible") or ""))} · source : {escape(str(kpi.get("source") or ""))}</div>'
            '</div>'
            '<div class="flex flex-wrap gap-1">'
        )
        for cell in strate.get("modules", []) or []:
            couleur = cell.get("couleur") if cell.get("couleur") in _CARTE_CELL_CLS else "gris"
            ckpi = cell.get("kpi", {}) or {}
            tooltip = (
                f'{cell.get("nom") or ""} — {ckpi.get("label") or ""} : {ckpi.get("valeur") or ""} '
                f'(cible : {ckpi.get("cible") or ""}) · source : {ckpi.get("source") or ""}'
            )
            if cell.get("preuve"):
                tooltip += f' · preuve : {cell["preuve"]}'
            lien = str(cell.get("lien") or "#")
            ext = ' target="_blank" rel="noopener"' if lien.startswith("http") else ""
            html += (
                f'<a href="{escape(lien)}"{ext} title="{escape(tooltip)}" '
                f'class="px-1.5 py-0.5 rounded text-[10px] font-medium leading-4 {_CARTE_CELL_CLS[couleur]} transition-colors">'
                f'{escape(str(cell.get("nom") or ""))}</a>'
            )
        html += '</div>'
        html += (
            f'<div class="mt-2 text-xs text-gray-400">{cpt.get("vert", 0)} vert · {cpt.get("jaune", 0)} jaune · '
            f'{cpt.get("rouge", 0)} rouge · {cpt.get("gris", 0)} gris — {cpt.get("total", 0)} modules</div>'
        )
        html += '</div>'

    for err in carte.get("errors", []) or []:
        html += f'<div class="bg-amber-50 border border-amber-200 rounded-xl px-4 py-2 mb-2 text-xs text-amber-700">Source dégradée : {escape(str(err))}</div>'
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
    """« Ce qui bloque » — le QG COMPTE et POINTE, il ne répète pas (refonte Alex 06/07).

    Source : var/blocages.json (collect_blocages.py, republié en /api/blocages.json).
    En tête : les compteurs par endroit avec le lien pour Y ALLER — aucun contenu
    répété depuis /decisions/, le Kanban ou GitHub. Seule exception développée sur
    place : les items sudo (ils ne vivent nulle part ailleurs) — texte complet,
    jamais tronqué, commande exacte en bloc code. Règle globale : ZÉRO ellipsis.
    En bas : les 10 dernières PRs mergées — la boucle de contrôle d'Alex.
    """
    payload = payload if isinstance(payload, dict) else {}
    blocages = payload.get("blocages") if isinstance(payload.get("blocages"), list) else []
    generated_at = str(payload.get("generated_at") or "non renseigné")

    def _count(pred) -> int:
        return sum(1 for b in blocages if isinstance(b, dict) and pred(b))

    n_decisions = _count(lambda b: b.get("type") == "decision")
    n_cartes = _count(lambda b: b.get("type") == "carte")
    n_cartes_alex = _count(lambda b: b.get("type") == "carte" and b.get("qui_debloque") == "alex")
    n_sudo = _count(lambda b: b.get("type") == "sudo")
    n_prs = _count(lambda b: b.get("type") == "pr")
    n_reworks = _count(lambda b: b.get("type") == "pr" and b.get("qui_debloque") == "agent")
    total = len(blocages)

    html = (
        '<div class="mb-6">'
        '<h1 class="text-xl font-bold text-gray-900">Ce qui bloque — compte et pointe</h1>'
        f'<p class="text-sm text-gray-500 mt-0.5">{total} blocage(s) au total. Cette page ne répète rien : '
        'elle compte par endroit et te donne le lien pour y aller. Seuls les items sudo sont développés ici '
        f'(ils ne vivent nulle part ailleurs) — source <a href="/api/blocages.json" class="text-blue-500 hover:underline">blocages.json</a> ({escape(generated_at)}).</p>'
        '</div>'
    )

    # ── Tableau de bord : gros chiffres + lien direct, zéro contenu répété ────
    kanban_detail = f"{n_cartes} bloquée(s)"
    if n_cartes_alex:
        kanban_detail += f", dont {n_cartes_alex} pour toi"
    pr_detail = f"{n_prs} en attente"
    if n_reworks:
        pr_detail += f", dont {n_reworks} rework(s) agent"
    gh_prs_url = "https://github.com/search?q=org%3Aomar-paris+is%3Apr+is%3Aopen&type=pullrequests"
    compteur_tuiles = [
        ("Décisions", n_decisions, "ouvertes" if n_decisions != 1 else "ouverte",
         "/decisions/", "y aller : /decisions/", False),
        ("Kanban", n_cartes, kanban_detail.split(" ", 1)[1],
         "https://hermes.omar.paris/kanban", "y aller : dashboard Kanban", True),
        ("Sudo", n_sudo, "en attente — le détail est ici",
         "#sudo", "liste complète ci-dessous", False),
        ("PRs ouvertes", n_prs, pr_detail.split(" ", 1)[1],
         gh_prs_url, "y aller : GitHub", True),
    ]
    html += '<div class="grid grid-cols-2 lg:grid-cols-4 gap-3 mb-8">'
    for label, n, detail, lien, lien_label, externe in compteur_tuiles:
        target = ' target="_blank" rel="noopener"' if externe else ""
        n_cls = "text-gray-300" if n == 0 else "text-gray-900"
        html += (
            f'<a href="{escape(lien)}"{target} class="block bg-white rounded-xl border border-gray-200 px-4 py-4 hover:border-blue-300 hover:shadow-sm transition">'
            f'<div class="text-xs font-semibold uppercase tracking-wide text-gray-500">{escape(label)}</div>'
            f'<div class="text-3xl font-bold {n_cls} mt-1">{n}</div>'
            f'<div class="text-xs text-gray-500 mt-0.5">{escape(detail)}</div>'
            f'<div class="text-xs text-blue-600 mt-2">{escape(lien_label)} &rarr;</div></a>'
        )
    html += '</div>'

    if total == 0:
        html += (
            '<div class="bg-green-50 border border-green-200 rounded-xl px-5 py-4 mb-8 text-sm text-green-700">'
            'Rien ne te bloque — le système avance seul.</div>'
        )

    # ── Pour toi : TA liste en clair + encart de réponse (demande Alex 06/07 :
    # « pouvoir ajouter la réponse juste en dessous — parfois juste dire c'est
    # fait, parfois expliquer pour que le système sache quoi faire après »).
    # Le compte-et-pointe vaut pour le bruit machine, pas pour la file d'Alex.
    # Les entrées origine autre VPS (type=vps) vivent dans la section Multi-VPS :
    # leur réponse passe par le VPS d'origine, pas par l'encart kanban local.
    alex_items = sorted(
        [b for b in blocages if isinstance(b, dict) and b.get("qui_debloque") == "alex" and b.get("type") != "vps"],
        key=lambda b: -(b.get("age_jours") or 0),
    )
    if alex_items:
        html += (
            '<div id="pour-toi" class="flex items-baseline gap-2 mb-2">'
            '<h2 class="text-sm font-bold uppercase tracking-wide text-amber-700">Pour toi — en clair, avec réponse directe</h2>'
            f'<span class="text-xs text-gray-400">{len(alex_items)} item(s) — réponds ici : « fait » suffit, ou explique pour orienter la suite</span></div>'
            '<div class="bg-white rounded-xl border border-amber-200 divide-y divide-gray-100 mb-8">'
        )
        for b in alex_items:
            ref = (b.get("refs") or [""])[0]
            titre = b.get("titre") or ""
            action = b.get("action_1_ligne") or ""
            age = b.get("age_jours")
            effort = b.get("effort_min")
            lien = b.get("lien") or ""
            meta_bits = []
            if age is not None:
                meta_bits.append(f"{int(age)} j")
            if effort:
                meta_bits.append(f"~{int(effort)} min")
            meta = " · ".join(meta_bits)
            badge = str(b.get("type") or "")
            rid = escape(ref.replace("#", "-"))
            html += (
                '<div class="px-5 py-4">'
                '<div class="flex items-baseline justify-between gap-3">'
                f'<div class="text-sm font-semibold text-gray-900">{escape(titre)}</div>'
                f'<div class="text-xs text-gray-400 whitespace-nowrap">{escape(badge)}{(" · " + escape(meta)) if meta else ""}</div></div>'
                + (f'<div class="text-sm text-gray-700 mt-1">{escape(action)}</div>' if action else "")
                + (f'<div class="text-xs mt-1"><a href="{escape(lien)}" class="text-blue-500 hover:underline" target="_blank" rel="noopener">ouvrir &rarr;</a></div>' if lien else "")
                + f'<div id="repzone-{rid}" class="mt-2 flex flex-wrap gap-2 items-center">'
                f'<input id="rep-{rid}" type="text" placeholder="ta réponse (optionnelle)…" '
                'class="flex-1 min-w-40 text-sm border border-gray-300 rounded-lg px-3 py-1.5">'
                f'<button onclick="repondreBlocage(\'{escape(ref)}\',\'{rid}\',true)" '
                'class="text-sm bg-green-600 text-white rounded-lg px-3 py-1.5 hover:bg-green-700">C&#39;est fait</button>'
                f'<button onclick="repondreBlocage(\'{escape(ref)}\',\'{rid}\',false)" '
                'class="text-sm bg-gray-800 text-white rounded-lg px-3 py-1.5 hover:bg-gray-900">Répondre</button>'
                '</div></div>'
            )
        html += '</div>'
        html += (
            '<script>async function repondreBlocage(ref, rid, fait){'
            'const inp=document.getElementById("rep-"+rid);'
            'let txt=(inp&&inp.value.trim())||"";'
            'let answer=fait?("FAIT"+(txt?" — "+txt:"")):txt;'
            'if(!answer){inp&&inp.focus();return;}'
            'const z=document.getElementById("repzone-"+rid);'
            'try{const r=await fetch("/api/blocages/answer",{method:"POST",'
            'headers:{"content-type":"application/json"},'
            'body:JSON.stringify({ref:ref,answer:answer})});'
            'if(r.ok){z.innerHTML=\'<span class="text-sm text-green-700">&#10003; Transmis — \'+answer.replace(/</g,"&lt;")+\' (le système reprend la main)</span>\';}'
            'else{z.insertAdjacentHTML("beforeend",\'<span class="text-xs text-red-600">Erreur — réessaie ou réponds en session.</span>\');}}'
            'catch(e){z.insertAdjacentHTML("beforeend",\'<span class="text-xs text-red-600">Erreur réseau.</span>\');}}'
            '</script>'
        )

    # ── Multi-VPS : blockers remontés par les rapports oa.vps-report/v1 des
    # autres VPS (jab, pantheos…), dédupliqués contre le local — badge d'origine.
    vps_items = sorted(
        [b for b in blocages if isinstance(b, dict) and b.get("type") == "vps"],
        key=lambda b: -(b.get("age_jours") or 0),
    )
    vps_stats = payload.get("vps_blockers") if isinstance(payload.get("vps_blockers"), dict) else {}
    if vps_items or vps_stats:
        html += (
            '<div id="multi-vps" class="flex items-baseline gap-2 mb-2">'
            '<h2 class="text-sm font-bold uppercase tracking-wide text-violet-700">Multi-VPS — remonté par les autres VPS</h2>'
            '<span class="text-xs text-gray-400">source rapports oa.vps-report/v1 · dédupliqué contre le kanban local · détail flotte sur /ops/</span></div>'
            '<div class="bg-white rounded-xl border border-violet-200 mb-8">'
        )
        if vps_stats:
            html += '<div class="px-5 py-3 border-b border-gray-100 text-xs text-gray-600 space-y-0.5">'
            for node in sorted(vps_stats):
                st = vps_stats[node] if isinstance(vps_stats[node], dict) else {}
                html += (
                    f'<div><span class="font-semibold uppercase">{escape(str(node))}</span> — '
                    f'{int(st.get("total") or 0)} blocker(s) rapporté(s) · '
                    f'{int(st.get("dedupliques") or 0)} déjà suivi(s) localement (dédupliqués) · '
                    f'{int(st.get("uniques") or 0)} propre(s) à ce VPS</div>'
                )
            html += '</div>'
        if vps_items:
            html += '<div class="divide-y divide-gray-100">'
            for b in vps_items:
                origine = str(b.get("origine") or "vps")
                qui = str(b.get("qui_debloque") or "")
                age = int(b.get("age_jours") or 0)
                html += (
                    '<div class="px-5 py-4">'
                    '<div class="flex items-baseline gap-2 flex-wrap">'
                    f'<span class="text-xs font-semibold rounded-full px-2 py-0.5 bg-violet-50 text-violet-700 border border-violet-200">origine {escape(origine)}</span>'
                    f'<span class="text-sm font-semibold text-gray-900">{escape(str(b.get("titre") or ""))}</span>'
                    f'<span class="text-xs text-gray-400">{age} j · débloque : {escape(qui)}</span></div>'
                    f'<div class="text-sm text-gray-700 mt-1">{escape(str(b.get("action_1_ligne") or ""))}</div>'
                    '</div>'
                )
            html += '</div>'
        else:
            html += ('<div class="px-5 py-3 text-sm text-gray-600">Aucun blocker propre à un autre VPS : '
                     'tout ce que les VPS remontent est déjà suivi dans le kanban local (badge « aussi signalé par » ci-dessus).</div>')
        html += '</div>'

    # ── Sudo : SEULE section développée — texte complet, jamais tronqué ───────
    sudo_items = sorted(
        [b for b in blocages if isinstance(b, dict) and b.get("type") == "sudo"],
        key=lambda b: -(b.get("age_jours") or 0),
    )
    if sudo_items:
        html += (
            '<div id="sudo" class="flex items-baseline gap-2 mb-2">'
            '<h2 class="text-sm font-bold uppercase tracking-wide text-red-700">Sudo — à toi seul</h2>'
            f'<span class="text-xs text-gray-400">{len(sudo_items)} item(s), texte intégral — ils ne vivent nulle part ailleurs</span></div>'
            '<div class="bg-white rounded-xl border border-gray-200 divide-y divide-gray-100 mb-8">'
        )
        for b in sudo_items:
            titre = escape(str(b.get("titre") or "Item sudo sans titre"))
            age = int(b.get("age_jours") or 0)
            age_cls = "text-red-600 font-semibold" if age >= 7 else ("text-amber-600" if age >= 3 else "text-gray-400")
            texte = str(b.get("texte_complet") or b.get("action_1_ligne") or "")
            commande = str(b.get("commande") or "")
            source = str(b.get("source") or "")
            html += (
                '<div class="px-5 py-4">'
                '<div class="flex items-baseline gap-2 flex-wrap">'
                f'<span class="text-sm font-semibold text-gray-900">{titre}</span>'
                f'<span class="text-xs {age_cls}">{age} j</span>'
                + (f'<span class="text-xs text-gray-400 font-mono">{escape(source)}</span>' if source else '')
                + '</div>'
                f'<div class="text-sm text-gray-700 mt-2 whitespace-pre-line">{escape(texte)}</div>'
            )
            if commande:
                html += (
                    '<div class="text-xs text-gray-500 mt-3 mb-1">Commande à copier :</div>'
                    f'<pre class="bg-gray-900 text-gray-100 rounded-lg px-4 py-3 text-xs overflow-x-auto"><code>{escape(commande)}</code></pre>'
                )
            html += '</div>'
        html += '</div>'

    # ── Dernières mergées — la boucle de contrôle d'Alex ──────────────────────
    mergees = payload.get("dernieres_mergees") if isinstance(payload.get("dernieres_mergees"), list) else []
    html += (
        '<div class="flex items-baseline gap-2 mb-2">'
        '<h2 class="text-sm font-bold uppercase tracking-wide text-gray-700">Dernières mergées — à contrôler</h2>'
        '<span class="text-xs text-gray-400">tu vérifies les résultats, tu n\'approuves plus</span></div>'
    )
    if mergees:
        html += '<div class="bg-white rounded-xl border border-gray-200 divide-y divide-gray-100">'
        for m in mergees:
            if not isinstance(m, dict):
                continue
            ref = escape(str(m.get("ref") or ""))
            url = str(m.get("url") or "")
            quand = str(m.get("merged_at") or "")[:16].replace("T", " ")
            lien = (f'<a href="{escape(url)}" target="_blank" rel="noopener" class="font-mono text-xs text-blue-600 hover:underline shrink-0">{ref}</a>'
                    if url else f'<span class="font-mono text-xs text-gray-600 shrink-0">{ref}</span>')
            html += (
                '<div class="px-4 py-2.5 flex items-baseline gap-3 flex-wrap">'
                f'{lien}'
                f'<span class="text-sm text-gray-800 flex-1 min-w-0">{escape(str(m.get("titre") or ""))}</span>'
                f'<span class="text-xs text-gray-400 shrink-0">{escape(quand)}</span>'
                '</div>'
            )
        html += '</div>'
    else:
        html += ('<div class="bg-amber-50 border border-amber-200 rounded-xl px-5 py-3 text-sm text-amber-700">'
                 'Aucun merge récupéré (gh indisponible ?) — voir les erreurs sources ci-dessous.</div>')

    errors = payload.get("errors") if isinstance(payload.get("errors"), list) else []
    if errors:
        html += (
            '<div class="mt-6 text-xs text-gray-400">Sources partielles : '
            + escape(" · ".join(str(e) for e in errors))
            + '</div>'
        )
    return html


def _daily_objective_model(objectifs: list, decisions: list, chantiers: list, blocages_payload: dict, builds: dict, agent_loop_audit: dict, ledger: dict) -> dict:
    """Calcule l'objectif du jour QG avec une logique explicable, pas un score magique."""
    open_decisions = [q for q in decisions if isinstance(q, dict) and q.get("statut") == "ouverte"]
    blocages_compteurs = blocages_payload.get("compteurs", {}) if isinstance(blocages_payload, dict) else {}
    alex_blocks = int(blocages_compteurs.get("pour_alex") or 0)
    total_blocks = int(blocages_compteurs.get("total") or blocages_compteurs.get("ouverts") or 0)
    agent_summary = agent_loop_audit.get("summary", {}) if isinstance(agent_loop_audit, dict) else {}
    gate_gaps = int(agent_summary.get("prs_without_gate") or 0) + int(agent_summary.get("builder_cards_without_gate") or 0)
    github_totals = ledger.get("github_totals", {}) if isinstance(ledger, dict) else {}
    prs_created = int(github_totals.get("prs_created") or 0)
    prs_merged = int(github_totals.get("prs_merged") or 0)
    build_failed = int(github_totals.get("build_failed") or 0)
    build_success = int(github_totals.get("build_success") or 0)
    build_today = int((builds.get("totals", {}) or {}).get("today") or 0) if isinstance(builds, dict) else 0

    risks = []
    if alex_blocks:
        risks.append(f"{alex_blocks} blocage(s) attendent Alex")
    if open_decisions:
        risks.append(f"{len(open_decisions)} décision(s) ouvertes")
    if gate_gaps:
        risks.append(f"{gate_gaps} gap(s) PR/gate")
    if build_failed:
        risks.append(f"{build_failed} build(s) en échec")

    if alex_blocks or open_decisions:
        title = "Débloquer le cockpit: décisions et blocages humains"
        why = "Tant que les décisions/blocages humains restent opaques, les agents produisent du bruit ou attendent."
        primary_link = "/decisions/" if open_decisions else "/blocages/"
    elif gate_gaps or build_failed:
        title = "Fermer les preuves: PR, gates Athena et builds"
        why = "La production existe mais n'est pas encore assez validée pour guider une release ou une décision sereine."
        primary_link = "/agent-loop/"
    elif prs_created and not prs_merged:
        title = "Transformer les PR du jour en livrables mergés ou explicitement bloqués"
        why = "Des changements ont été produits; l'objectif est maintenant de les conclure avec gate, merge ou décision claire."
        primary_link = "/builds/"
    else:
        title = "Produire un livrable prouvé qui rapproche le revenu OA"
        why = "Aucun blocage dominant ne ressort; le meilleur objectif est un artefact testé, relié à AppOmar/QG/client."
        primary_link = "/chantiers/"

    penalty = min(55, alex_blocks * 12 + len(open_decisions) * 6 + gate_gaps * 8 + build_failed * 10 + max(0, total_blocks - alex_blocks) * 2)
    bonus = min(25, prs_merged * 10 + build_success * 2 + build_today * 2)
    score = max(0, min(100, 65 - penalty + bonus))
    if score >= 75:
        tone = "vert"
    elif score >= 45:
        tone = "jaune"
    else:
        tone = "rouge"

    actions = []
    if open_decisions:
        first = open_decisions[0]
        actions.append({"label": "Trancher la première décision ouverte", "detail": str(first.get("texte", "Décision ouverte"))[:180], "href": "/decisions/"})
    if alex_blocks or total_blocks:
        actions.append({"label": "Lire les vrais blocages", "detail": f"{total_blocks or alex_blocks} blocage(s) à qualifier avec cause, owner, preuve, next action.", "href": "/blocages/"})
    if gate_gaps or build_failed:
        actions.append({"label": "Fermer les gates/preuves", "detail": f"{gate_gaps} gap(s) gate, {build_failed} build(s) failed.", "href": "/agent-loop/"})
    actions.append({"label": "Choisir le livrable prouvé du jour", "detail": "Un livrable = PR/test/rapport/gate, pas une intention de plus.", "href": "/chantiers/"})

    return {
        "schema": "oa.qg.daily-objective/v1",
        "title": title,
        "why": why,
        "score": score,
        "tone": tone,
        "primary_link": primary_link,
        "signals": {
            "alex_blocks": alex_blocks,
            "total_blocks": total_blocks,
            "open_decisions": len(open_decisions),
            "gate_gaps": gate_gaps,
            "prs_created": prs_created,
            "prs_merged": prs_merged,
            "build_success": build_success,
            "build_failed": build_failed,
            "builds_today": build_today,
        },
        "risks": risks,
        "actions": actions[:5],
    }


def page_productivite(model: dict, ledger: dict) -> str:
    score = int(model.get("score") or 0)
    tone = model.get("tone") or "jaune"
    tone_cls = {"vert": "bg-green-50 border-green-200 text-green-800", "jaune": "bg-amber-50 border-amber-200 text-amber-800", "rouge": "bg-red-50 border-red-200 text-red-800"}.get(tone, "bg-slate-50 border-slate-200 text-slate-800")
    signals = model.get("signals", {}) if isinstance(model.get("signals"), dict) else {}
    risks = model.get("risks", []) or []
    actions = model.get("actions", []) or []
    cards = "".join(
        f'<div class="bg-white rounded-xl border border-gray-200 px-4 py-3"><div class="text-2xl font-bold text-gray-900">{escape(str(v))}</div><div class="text-xs text-gray-500 mt-1">{escape(str(k).replace("_", " "))}</div></div>'
        for k, v in signals.items()
    )
    risk_html = "".join(f'<li>{escape(str(r))}</li>' for r in risks) or '<li>Aucun risque dominant détecté dans les signaux QG.</li>'
    action_html = "".join(
        f'<a href="{escape(str(a.get("href", "#")))}" class="block bg-white rounded-xl border border-gray-200 px-4 py-3 hover:border-blue-300 hover:shadow-sm"><div class="text-sm font-semibold text-gray-900">{escape(str(a.get("label", "Action")))}</div><div class="text-xs text-gray-500 mt-1">{escape(str(a.get("detail", "")))}</div></a>'
        for a in actions
    )
    return f'''
<div class="flex items-center justify-between mb-6">
  <div>
    <h1 class="text-xl font-bold text-gray-900">Objectif du jour</h1>
    <p class="text-sm text-gray-500 mt-0.5">Calcul explicable à partir des décisions, blocages, gates, PR et builds du QG.</p>
  </div>
  <a href="/api/productivite.json" class="text-xs font-medium text-blue-600 hover:underline">API JSON</a>
</div>

<div class="rounded-2xl border px-5 py-5 mb-5 {tone_cls}">
  <div class="text-xs uppercase tracking-wide font-semibold opacity-70">Objectif recommandé</div>
  <div class="text-2xl font-bold mt-1">{escape(str(model.get("title", "Objectif non calculé")))}</div>
  <div class="text-sm mt-2 max-w-3xl">{escape(str(model.get("why", "")))}</div>
  <div class="mt-4 flex items-center gap-3">
    <div class="text-4xl font-black">{score}</div>
    <div class="text-xs uppercase tracking-wide font-semibold">score productivité<br>du jour</div>
    <a href="{escape(str(model.get("primary_link", "/")))}" class="ml-auto rounded-lg bg-white/70 border border-current/20 px-3 py-2 text-xs font-semibold hover:bg-white">Ouvrir la page utile →</a>
  </div>
</div>

<div class="grid md:grid-cols-4 gap-3 mb-5">{cards}</div>

<div class="grid lg:grid-cols-2 gap-4">
  <section class="bg-white rounded-xl border border-gray-200 px-5 py-4">
    <h2 class="text-sm font-bold text-gray-900 mb-2">Pourquoi ce score ?</h2>
    <ul class="list-disc pl-5 text-sm text-gray-600 space-y-1">{risk_html}</ul>
  </section>
  <section class="bg-white rounded-xl border border-gray-200 px-5 py-4">
    <h2 class="text-sm font-bold text-gray-900 mb-2">Règle CTO</h2>
    <p class="text-sm text-gray-600">L'objectif du jour n'est pas “faire beaucoup”. C'est réduire l'incertitude la plus coûteuse avec un livrable vérifiable.</p>
  </section>
</div>

<h2 class="text-sm font-semibold text-gray-700 mt-6 mb-2 uppercase tracking-wide">Plan immédiat</h2>
<div class="grid md:grid-cols-2 gap-3">{action_html}</div>
'''


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
            html += '<div class="flex items-start justify-between gap-3 mb-2">'
            html += f'<div class="text-sm font-semibold text-gray-900 leading-snug">{escape(q["texte"])}</div>'
            html += f'<span class="shrink-0 rounded-full bg-slate-100 text-slate-600 border border-slate-200 px-2 py-0.5 text-[11px] font-semibold">{escape(str(q.get("type") or "decision"))}</span>'
            html += '</div>'
            if q.get("options"):
                html += '<div class="flex flex-wrap gap-1.5 mb-2">'
                for opt in q.get("options", [])[:4]:
                    html += f'<span class="rounded-full bg-blue-50 text-blue-700 border border-blue-100 px-2 py-0.5 text-[11px] font-medium">{escape(str(opt))}</span>'
                html += '</div>'
            if q.get("contexte"):
                ctx = escape(str(q["contexte"]))
                html += ('<details class="mb-2 rounded-lg border border-slate-100 bg-slate-50 px-3 py-2">'
                         '<summary class="cursor-pointer text-xs font-semibold text-slate-700">Pourquoi / impact / source</summary>'
                         f'<div class="mt-2 whitespace-pre-wrap text-xs text-slate-600 leading-relaxed">{ctx}</div></details>')
            if q.get("blocked_ref"):
                html += f'<div class="text-xs text-amber-700 bg-amber-50 border border-amber-100 rounded-lg px-3 py-1.5 mb-2">⏸ bloque : {escape(q["blocked_ref"])}</div>'
            else:
                html += '<div class="text-xs text-slate-400 mb-2">Pas de carte/issue liée — décision informative ou à recanoniser.</div>'
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
    html += f'''<script>
function esc(s){{
  const d = document.createElement("div");
  d.textContent = String(s);
  return d.innerHTML;
}}
function answerClosed(id, opt){{
  const c = document.getElementById("compl-"+id);
  answer(id, opt + (c && c.value.trim() ? " — " + c.value.trim() : ""));
}}
async function answer(id, val){{
  if(!val || !val.trim()){{ return; }}
  const c = document.getElementById("card-"+id);
  let r, payload = {{}};
  try{{
    r = await fetch("{api}", {{method:"POST", headers:{{"content-type":"application/json"}}, body: JSON.stringify({{id:id, answer:val}})}});
    try{{ payload = await r.json(); }}catch(e){{ payload = {{error:"réponse API illisible"}}; }}
  }}catch(e){{
    c.innerHTML += '<div class="text-xs text-red-700 bg-red-50 border border-red-100 rounded-lg px-3 py-2 mt-2">Erreur réseau/API — ' + esc(e.message || e) + '</div>';
    return;
  }}
  if(r.ok){{
    c.innerHTML = '<div class="text-sm text-green-700 bg-green-50 border border-green-100 rounded-lg px-3 py-2">✓ Réponse envoyée — ' + esc(val) + ' (processus débloqué)</div>';
  }}else{{
    const msg = payload.error || ("HTTP " + r.status);
    c.innerHTML += '<div class="text-xs text-red-700 bg-red-50 border border-red-100 rounded-lg px-3 py-2 mt-2">Erreur API — ' + esc(msg) + '</div>';
  }}
}}
</script>'''
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
        f'<p class="text-sm text-gray-500 mt-0.5">Issue ↔ Kanban ↔ PR ↔ Gate — dernier scan {escape(str(checked_at))} · figé depuis le 15/06 si non recronifié.</p></div>'
        '<div class="flex gap-3"><a href="/agent-activity/" class="text-xs text-blue-600 hover:underline font-semibold">Activité agents dynamique</a><a href="/api/agent-loop-registry.json" class="text-xs text-blue-500 hover:underline">API registry</a><a href="/api/agent-loop-audit.json" class="text-xs text-blue-500 hover:underline">API audit</a></div></div>'
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


def page_agent_activity(activity: dict) -> str:
    """Vue QG dynamique: qui fait quoi, par agent/VPS/type/date/priorité."""
    activity = activity if isinstance(activity, dict) else {}
    summary = activity.get("summary") or {}
    agents = activity.get("agents") or []
    active_items = activity.get("active_items") or []
    decisions = activity.get("decision_required") or []
    items = activity.get("items") or []
    generated_at = activity.get("generated_at") or "non généré"
    filters = activity.get("filters") or {}

    def filter_select(label: str, field: str, values: list) -> str:
        options = ''.join(f'<option value="{escape(str(v))}">{escape(str(v))}</option>' for v in values if str(v))
        return (
            f'<label class="text-xs font-semibold text-gray-600">{escape(label)}'
            f'<select data-agent-activity-filter="{escape(field)}" class="mt-1 w-full rounded-lg border border-gray-200 bg-white px-2 py-1.5 text-xs text-gray-700">'
            '<option value="">Tous</option>' + options + '</select></label>'
        )

    def kpi(label: str, value: object, sub: str = "") -> str:
        sub_html = f'<div class="text-xs text-gray-400 mt-1">{escape(sub)}</div>' if sub else ""
        return f'<div class="bg-white rounded-xl border border-gray-200 px-4 py-3"><div class="text-2xl font-bold text-gray-900">{escape(str(value))}</div><div class="text-xs text-gray-500 mt-0.5">{escape(label)}</div>{sub_html}</div>'

    def pill(text: object, tone: str = "gray") -> str:
        classes = {
            "green": "bg-green-50 text-green-700 border-green-200",
            "amber": "bg-amber-50 text-amber-700 border-amber-200",
            "red": "bg-red-50 text-red-700 border-red-200",
            "blue": "bg-blue-50 text-blue-700 border-blue-200",
            "gray": "bg-gray-50 text-gray-600 border-gray-200",
        }.get(tone, "bg-gray-50 text-gray-600 border-gray-200")
        return f'<span class="inline-flex rounded-full border px-2 py-0.5 text-[11px] font-semibold {classes}">{escape(str(text))}</span>'

    def item_row(item: dict) -> str:
        status = str(item.get("status") or "unknown")
        tone = "green" if status == "done" else "red" if status == "blocked" else "blue" if status == "running" else "amber" if status in {"ready", "scheduled", "todo"} else "gray"
        artifacts = item.get("artifacts") or []
        artifact_txt = f'{len(artifacts)} artefact(s)' if artifacts else "aucun artefact"
        result = str(item.get("result_excerpt") or "")
        result_html = f'<div class="text-xs text-gray-500 mt-1">{escape(result)}</div>' if result else ""
        return (
            '<div class="agent-activity-item px-4 py-3 border-b border-gray-100 last:border-0" '
            f'data-agent="{escape(str(item.get("assignee") or "unassigned"))}" '
            f'data-vps="{escape(str(item.get("vps") or "unknown"))}" '
            f'data-application="{escape(str(item.get("application") or "unknown"))}" '
            f'data-activity-type="{escape(str(item.get("activity_type") or "work"))}" '
            f'data-status="{escape(status)}" '
            f'data-priority="{escape(str(item.get("priority_bucket") or "P?"))}" '
            f'data-latest="{escape(str(item.get("latest_at") or ""))}">'
            '<div class="flex flex-wrap items-start justify-between gap-2">'
            f'<div><div class="text-sm font-semibold text-gray-900">{escape(str(item.get("title") or ""))}</div>'
            f'<div class="text-xs text-gray-400 font-mono mt-0.5">{escape(str(item.get("task_id") or ""))} · {escape(str(item.get("latest_at") or "?"))}</div></div>'
            f'<div class="flex flex-wrap gap-1.5 justify-end">{pill(status, tone)}{pill(item.get("priority_bucket") or "P?", "amber")}{pill(item.get("vps") or "unknown", "blue")}{pill(item.get("activity_type") or "work", "gray")}</div>'
            '</div>'
            f'<div class="mt-2 text-xs text-gray-600">agent <span class="font-semibold">{escape(str(item.get("assignee") or "unassigned"))}</span> · app <span class="font-semibold">{escape(str(item.get("application") or "unknown"))}</span> · {escape(artifact_txt)}</div>'
            + result_html + '</div>'
        )

    agent_rows = ""
    for agent in agents[:30] if isinstance(agents, list) else []:
        priorities = agent.get("priorities") or {}
        apps = agent.get("applications") or {}
        app_txt = ", ".join(f"{k}:{v}" for k, v in sorted(apps.items(), key=lambda kv: str(kv[0]))[:4]) or "unknown"
        role = str(agent.get("role") or "rôle non déclaré")
        agent_rows += (
            '<div class="px-4 py-3 border-b border-gray-100 last:border-0">'
            '<div class="flex flex-wrap items-center justify-between gap-2">'
            f'<div><div class="text-sm font-bold text-gray-900">{escape(str(agent.get("agent") or "agent"))}</div><div class="text-xs text-gray-500">{escape(role)}</div></div>'
            f'<div class="flex flex-wrap gap-1.5">{pill("actif " + str(agent.get("active", 0)), "blue")}{pill("done " + str(agent.get("done", 0)), "green")}{pill("bloqué " + str(agent.get("blocked", 0)), "red" if agent.get("blocked") else "gray")}{pill(agent.get("dominant_vps") or "unknown", "blue")}</div>'
            '</div>'
            f'<div class="text-xs text-gray-500 mt-2">types: {escape(str(agent.get("types") or {}))} · priorités: {escape(str(priorities))} · apps: {escape(app_txt)} · dernier: {escape(str(agent.get("latest_at") or "?"))}</div>'
            '</div>'
        )
    if not agent_rows:
        agent_rows = '<div class="px-4 py-4 text-sm text-amber-700 bg-amber-50">Aucune activité agent lisible.</div>'

    active_rows = "".join(item_row(i) for i in active_items[:30] if isinstance(i, dict)) or '<div class="px-4 py-4 text-sm text-green-700 bg-green-50">Aucune carte active/bloquée dans la fenêtre.</div>'
    decision_rows = "".join(item_row(i) for i in decisions[:20] if isinstance(i, dict)) or '<div class="px-4 py-4 text-sm text-green-700 bg-green-50">Aucune décision bloquante détectée.</div>'
    recent_rows = "".join(item_row(i) for i in items[:40] if isinstance(i, dict)) or '<div class="px-4 py-4 text-sm text-gray-500">Aucun item récent.</div>'

    errors = activity.get("errors") or []
    errors_html = ""
    if errors:
        errors_html = '<div class="bg-amber-50 border border-amber-200 rounded-xl px-4 py-3 mb-5"><div class="text-sm font-bold text-amber-800">Collecte dégradée</div>'
        errors_html += "".join(f'<div class="text-xs font-mono text-amber-700 mt-1">{escape(str(e))}</div>' for e in errors[:6])
        errors_html += '</div>'

    by_vps = summary.get("by_vps") or {}
    by_type = summary.get("by_type") or {}
    by_vps_txt = " · ".join(f"{k}: {v}" for k, v in by_vps.items()) or "unknown"
    by_type_txt = " · ".join(f"{k}: {v}" for k, v in by_type.items()) or "unknown"
    filter_controls = (
        '<div class="bg-white rounded-xl border border-gray-200 px-4 py-3 mb-5">'
        '<div class="flex flex-wrap items-center justify-between gap-2 mb-3"><div><div class="text-sm font-bold text-gray-900">Filtres dynamiques</div><div class="text-xs text-gray-400">Filtre les listes visibles sans exposer plus de données.</div></div>'
        '<button type="button" data-agent-activity-reset class="rounded-lg border border-gray-200 px-3 py-1.5 text-xs font-semibold text-gray-600 hover:border-blue-200 hover:text-blue-700">Réinitialiser</button></div>'
        '<div class="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-7 gap-3">'
        + filter_select("Agent", "agent", filters.get("agents") or [])
        + filter_select("VPS", "vps", filters.get("vps") or [])
        + filter_select("Application", "application", filters.get("applications") or [])
        + filter_select("Type", "activityType", filters.get("activity_types") or [])
        + filter_select("Statut", "status", filters.get("statuses") or [])
        + filter_select("Priorité", "priority", filters.get("priority_buckets") or [])
        + '<label class="text-xs font-semibold text-gray-600">Date<select data-agent-activity-filter="date" class="mt-1 w-full rounded-lg border border-gray-200 bg-white px-2 py-1.5 text-xs text-gray-700"><option value="">Toutes</option><option value="24h">24h</option><option value="open">Actives/ouvertes</option></select></label>'
        + '</div><div class="mt-3 text-xs text-gray-500"><span data-agent-activity-count></span></div></div>'
    )
    filter_script = """
<script>
(() => {
  const selects = [...document.querySelectorAll('[data-agent-activity-filter]')];
  const rows = [...document.querySelectorAll('.agent-activity-item')];
  const count = document.querySelector('[data-agent-activity-count]');
  const reset = document.querySelector('[data-agent-activity-reset]');
  function isRecent24(value) {
    if (!value) return false;
    const t = Date.parse(value);
    if (Number.isNaN(t)) return false;
    return Date.now() - t <= 24 * 60 * 60 * 1000;
  }
  function matches(row, field, value) {
    if (!value) return true;
    if (field === 'date') {
      if (value === '24h') return isRecent24(row.dataset.latest || '');
      if (value === 'open') return ['running','ready','todo','scheduled','blocked'].includes(row.dataset.status || '');
      return true;
    }
    return (row.dataset[field] || '') === value;
  }
  function applyFilters() {
    const active = Object.fromEntries(selects.map(s => [s.dataset.agentActivityFilter, s.value]));
    let visible = 0;
    rows.forEach(row => {
      const ok = Object.entries(active).every(([field, value]) => matches(row, field, value));
      row.hidden = !ok;
      if (ok) visible += 1;
    });
    if (count) count.textContent = `${visible}/${rows.length} lignes visibles`;
  }
  selects.forEach(s => s.addEventListener('change', applyFilters));
  if (reset) reset.addEventListener('click', () => { selects.forEach(s => { s.value = ''; }); applyFilters(); });
  applyFilters();
})();
</script>
"""

    return (
        '<div class="flex items-center justify-between mb-6"><div>'
        '<h1 class="text-xl font-bold text-gray-900">Activité agents — cockpit dynamique</h1>'
        f'<p class="text-sm text-gray-500 mt-0.5">Qui fait quoi, où, avec quelle priorité — snapshot {escape(str(generated_at))}.</p></div>'
        '<div class="flex gap-3"><a href="/api/agent-activity.json" class="text-xs text-blue-600 hover:underline font-semibold">API agent-activity</a><a href="/agent-loop/" class="text-xs text-blue-500 hover:underline">Audit anti-orphelins</a></div></div>'
        + errors_html +
        '<div class="grid grid-cols-2 lg:grid-cols-6 gap-3 mb-5">'
        + kpi("Tâches fenêtre", summary.get("tasks", 0), "Kanban 7 jours + actifs")
        + kpi("Actives", summary.get("active", 0), "running/ready/todo/scheduled/blocked")
        + kpi("Bloquées", summary.get("blocked", 0), "owner/next_action à vérifier")
        + kpi("Décisions", summary.get("decision_required", 0), "GO ou blocage")
        + kpi("Agents", summary.get("agents", 0), "assignees actifs")
        + kpi("Done", summary.get("done", 0), "livrés dans fenêtre")
        + '</div>'
        + f'<div class="bg-slate-50 border border-slate-200 rounded-xl px-4 py-3 mb-5 text-xs text-slate-600"><span class="font-semibold">Dimensions de pilotage :</span> agent, VPS, application, type, statut, priorité, date. <span class="font-semibold">VPS :</span> {escape(by_vps_txt)}. <span class="font-semibold">Types :</span> {escape(by_type_txt)}.</div>'
        + filter_controls
        + '<section class="bg-white rounded-xl border border-gray-200 overflow-hidden mb-6"><div class="px-4 py-3 border-b border-gray-100"><div class="text-sm font-bold text-gray-900">Par agent — responsabilité et charge</div><div class="text-xs text-gray-400">Synthèse depuis Kanban + registry agents.</div></div>' + agent_rows + '</section>'
        + '<section class="bg-white rounded-xl border border-gray-200 overflow-hidden mb-6"><div class="px-4 py-3 border-b border-gray-100"><div class="text-sm font-bold text-gray-900">À regarder maintenant</div><div class="text-xs text-gray-400">Cartes actives, prêtes, planifiées ou bloquées.</div></div>' + active_rows + '</section>'
        + '<section class="bg-white rounded-xl border border-red-200 overflow-hidden mb-6"><div class="px-4 py-3 border-b border-red-100 bg-red-50"><div class="text-sm font-bold text-red-900">Décisions / blocages</div><div class="text-xs text-red-700">Ce qui peut nécessiter Alex ou H-Omar.</div></div>' + decision_rows + '</section>'
        + '<section class="bg-white rounded-xl border border-gray-200 overflow-hidden"><div class="px-4 py-3 border-b border-gray-100"><div class="text-sm font-bold text-gray-900">Journal récent</div><div class="text-xs text-gray-400">Derniers items redacted, avec livrables et artefacts quand présents.</div></div>' + recent_rows + '</section>'
        + filter_script
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


def _private_directory(path: Path) -> Path:
    """Create or validate a user-owned 0700 directory without following links."""
    try:
        os.mkdir(path, 0o700)
    except FileExistsError:
        pass
    info = os.lstat(path)
    if (
        not stat.S_ISDIR(info.st_mode)
        or info.st_uid != os.getuid()
        or info.st_mode & 0o077
    ):
        raise RuntimeError(f"unsafe QG build lock directory: {path}")
    return path


def _resolved_outside_root(path: Path) -> Path | None:
    """Resolve an existing path and reject the checkout and its descendants."""
    try:
        resolved_path = path.resolve(strict=True)
        resolved_root = ROOT.resolve(strict=True)
    except (OSError, RuntimeError):
        return None
    if resolved_path.is_relative_to(resolved_root):
        return None
    return resolved_path


def _fallback_runtime_dir() -> Path | None:
    """Find an existing fallback parent outside the resolved checkout."""
    try:
        resolved_root = ROOT.resolve(strict=True)
        candidate = Path(tempfile.gettempdir()).resolve(strict=True)
    except (OSError, RuntimeError):
        return None
    while candidate.is_relative_to(resolved_root):
        parent = candidate.parent
        if parent == candidate:
            return None
        candidate = parent
    return candidate


def _secure_xdg_runtime_dir() -> Path | None:
    raw_runtime = os.environ.get("XDG_RUNTIME_DIR")
    if not raw_runtime:
        return None
    runtime_dir = Path(raw_runtime)
    if not runtime_dir.is_absolute():
        return None
    try:
        info = os.lstat(runtime_dir)
    except FileNotFoundError:
        return None
    if (
        not stat.S_ISDIR(info.st_mode)
        or info.st_uid != os.getuid()
        or info.st_mode & 0o077
    ):
        return None
    return _resolved_outside_root(runtime_dir)


def build_lock_path(out_root: Path) -> Path:
    """Return a stable advisory-lock path outside the Git checkout.

    A flock file is an inode used as a mutex, not an indication that a writer is
    currently active.  It must stay stable between processes; unlinking it after
    releasing the lock would allow two processes to lock different inodes.  Keep
    these persistent mutex files under ignored runtime state instead of beside
    ``public/``, where they would make the canonical checkout dirty.
    """
    import hashlib

    output_id = hashlib.sha256(str(out_root.resolve()).encode("utf-8")).hexdigest()[:16]
    runtime_dir = _secure_xdg_runtime_dir()
    if runtime_dir is None:
        runtime_dir = _fallback_runtime_dir()
        if runtime_dir is None:
            raise RuntimeError("no safe QG build lock runtime outside checkout")
        lock_dir = runtime_dir / f"oa-qg-build-locks-{os.getuid()}"
    else:
        lock_dir = runtime_dir / "oa-qg-build-locks"
    _private_directory(lock_dir)
    if _resolved_outside_root(lock_dir) is None:
        raise RuntimeError("unsafe QG build lock directory under checkout")
    return lock_dir / f"qg-build-{output_id}.lock"


@contextmanager
def build_lock(out_root: Path):
    """Hold a stable, private advisory lock for one QG output directory."""
    import fcntl

    lock_path = build_lock_path(out_root)
    flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(lock_path, flags, 0o600)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
            raise RuntimeError(f"unsafe QG build lock file: {lock_path}")
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "a+") as lock_fh:
            fd = -1
            fcntl.flock(lock_fh.fileno(), fcntl.LOCK_EX)
            yield
    finally:
        if fd != -1:
            os.close(fd)


def main(argv: list[str] | None = None) -> None:
    out_root = build_output_dir()
    out_root.parent.mkdir(parents=True, exist_ok=True)
    with build_lock(out_root):
        _main_locked(argv, out_root)


def _main_locked(argv: list[str] | None, out_root: Path) -> None:
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

    # Carte du puzzle (vision Alex 07/07) : collectée juste après payload() pour
    # recevoir l'inventaire apps FRAIS (le snapshot public/ date du build
    # précédent) — best-effort comme collect_blocages, ne casse jamais le build.
    try:
        carte_payload = _load_carte_collector().collect(
            write=True, app_inventory=data.get("vps_app_inventory")
        )
    except Exception as exc:  # ne casse jamais le build QG
        carte_payload = _read_var_json("carte.json")
        if not isinstance(carte_payload, dict) or not carte_payload:
            carte_payload = {
                "schema": "oa.carte/1",
                "generated_at": built_at,
                "regle_couleurs": {},
                "kpi_global": {},
                "strates": [],
                "errors": [f"carte_unavailable: {exc.__class__.__name__}"],
            }
    ledger = daily_ledger(data, built_at)
    ledger_history = _merge_daily_ledgers(ledger, previous_ledgers)

    tmp = out_root.parent / f".{out_root.name}_build_tmp"
    if tmp.exists():
        import shutil
        shutil.rmtree(tmp)
    (tmp / "api").mkdir(parents=True)
    docs_index = collect_public_docs(tmp)

    (tmp / "api" / "core-repos.json").write_text(
        json.dumps(redact_public_api_payload(data), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (tmp / "api" / "vps-app-inventory.json").write_text(
        json.dumps(data.get("vps_app_inventory", {}), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    # Republie les sorties des crons triage/vps-doctor (public/ est détruit à chaque build).
    # En worktree propre, ROOT/var est souvent absent: on conserve alors le snapshot public/api existant.
    for var_name in ("triage.json", "vps.json", "decisions.json", "objectifs.json", "chantiers.json", "boucles.json", "manifeste.json", "builder-pr-autogate.json", "oa-fleet-supervision-v0.json", "vps-resource-onboarding-v0.json"):
        var_payload = _read_var_json(var_name)
        if var_payload:
            if var_name == "vps-resource-onboarding-v0.json":
                var_payload = sanitize_resource_onboarding_public(var_payload)
            if var_name == "oa-fleet-supervision-v0.json":
                _inject_graded_conformity(var_payload)  # conformité 4 couleurs (Omar)
            (tmp / "api" / var_name).write_text(json.dumps(var_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    # Blocages : snapshot collecté en tête de build → /api/blocages.json.
    (tmp / "api" / "blocages.json").write_text(
        json.dumps(blocages_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    # Carte du puzzle : snapshot collecté en tête de build → /api/carte.json.
    (tmp / "api" / "carte.json").write_text(
        json.dumps(carte_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
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

    # Couche OBJECTIFS (qg) : ce qu'Alex vise. var/ runtime, fallback snapshot figé 14/06.
    objectifs = _read_var_json("objectifs.json")
    if not isinstance(objectifs, list):
        objectifs = [
            {"id": "jab-servi", "titre": "JAB pleinement servi", "statut": "en_cours", "progression": 55, "description": "Le premier client (JAB) recoit le service complet : facturation PennyLane, relais Maryse, presence Google MyBusiness. CRM en place avant la visite Jean-Alex.", "decisions_liees": ["2fa0610f95", "46cb4e7dc1", "b17cd03aed"]},
            {"id": "maturite-3-vps", "titre": "Maturite des 3 VPS", "statut": "en_cours", "progression": 40, "description": "VPS-OA (core), VPS clients (CCCU/JAB) et Pantheos (vie personnelle, sites Theo/Hugo/Victoria, H-Aurel) operationnels, observables et sauvegardes.", "decisions_liees": ["25f69efa80", "14192085d0", "d9beee76e6"]},
            {"id": "catalogue-10-apps", "titre": "Catalogue 10 apps reelles", "statut": "a_faire", "progression": 15, "description": "Transformer les stubs du catalogue en bundles reels et utilisables par les clients (priorite marketing actuellement a 0%).", "decisions_liees": ["447fac7271", "46cb4e7dc1"]},
            {"id": "observabilite-langfuse", "titre": "Observabilite Langfuse", "statut": "a_faire", "progression": 10, "description": "Tracage et observabilite des agents et pipelines LLM via Langfuse, pour mesurer cout, latence et qualite des boucles d'agents.", "decisions_liees": []},
        ]
    (tmp / "api" / "objectifs.json").write_text(json.dumps(objectifs, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

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

    try:
        agent_activity = _load_agent_activity().collect(window_days=7, limit=240)
    except Exception as exc:  # ne casse jamais le build QG
        agent_activity = {
            "schema": "oa.agent-activity/v1",
            "status": "degraded",
            "generated_at": built_at,
            "source": {"collector": "scripts/agent_activity.py"},
            "mode": "dynamic-readonly-redacted",
            "window_days": 7,
            "summary": {"tasks": 0, "active": 0, "blocked": 0, "done": 0, "agents": 0, "decision_required": 0, "by_status": {}, "by_priority": {}, "by_vps": {}, "by_type": {}},
            "filters": {"agents": [], "vps": [], "applications": [], "activity_types": [], "statuses": [], "priority_buckets": []},
            "agents": [],
            "active_items": [],
            "decision_required": [],
            "items": [],
            "errors": [f"agent-activity unavailable: {exc.__class__.__name__}: {exc}"],
        }
    (tmp / "api" / "agent-activity.json").write_text(
        json.dumps(agent_activity, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
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

    # Flotte VPS (rescue J4 07/07) : qui rapporte, qui dérive, qui est muet.
    try:
        vps_fleet = collect_vps_fleet(built_at)
    except Exception as exc:  # ne casse jamais le build QG
        vps_fleet = {
            "schema": "oa.vps-fleet-status/1",
            "built_at": built_at,
            "summary": {"expected": len(VPS_FLEET_EXPECTED), "nodes": 0, "reporting": 0, "en_derive": 0, "muets": len(VPS_FLEET_EXPECTED), "standards_fail": 0},
            "nodes": [],
            "errors": [f"vps_fleet_unavailable: {exc.__class__.__name__}"],
        }
    (tmp / "api" / "ops" / "vps-fleet.json").write_text(
        json.dumps(vps_fleet, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    # HubFleet reports v1 : maturité synthétique QG, sans duplication de logs locaux.
    try:
        hub_node_maturity = collect_hub_node_maturity(built_at)
    except Exception as exc:  # ne casse jamais le build QG
        hub_node_maturity = {
            "schema": "oa.qg.hub-node-maturity/1",
            "built_at": built_at,
            "source": "oa.hub-node-report/v1 redacted reports; no local logs duplicated",
            "summary": {"expected": len(HUB_NODE_EXPECTED), "reporting": 0, "missing": len(HUB_NODE_EXPECTED), "unknown": len(HUB_NODE_EXPECTED), "avg_score": None, "priority_gaps": 0},
            "nodes": [],
            "errors": [f"hub_node_maturity_unavailable: {exc.__class__.__name__}"],
        }
    (tmp / "api" / "ops" / "hub-node-maturity.json").write_text(
        json.dumps(hub_node_maturity, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    # Builds du jour (commits par repo, 7 j) → public/api/builds.json
    try:
        builds = _load_build_ledger().collect_builds()
    except Exception as exc:  # ne casse jamais le build du QG
        builds = {"totals": {"today": 0, "window": 0, "repos_today": 0, "repos_total": 0}, "today": "", "days": [], "deploys": [], "error": str(exc)}
    (tmp / "api" / "builds.json").write_text(
        json.dumps(builds, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    blocages_compteurs = blocages_payload.get("compteurs", {}) if isinstance(blocages_payload, dict) else {}
    try:
        pending_alex_actions = int(blocages_compteurs.get("pour_alex") or 0)
    except Exception:
        pending_alex_actions = 0
    builds_today = (builds.get("totals", {}) or {}).get("today", 0)

    productivite = _daily_objective_model(objectifs, decisions, chantiers, blocages_payload, builds, agent_loop_audit, ledger)
    (tmp / "api" / "productivite.json").write_text(
        json.dumps(productivite, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    oa_system_contracts = collect_oa_system_contracts(built_at)
    (tmp / "api" / "oa-system-contracts.json").write_text(
        json.dumps(oa_system_contracts, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    qg_cockpit = collect_qg_cockpit(
        built_at=built_at,
        decisions=decisions,
        blocages=blocages_payload,
        agent_activity=agent_activity,
        agent_loop_audit=agent_loop_audit,
        contracts=oa_system_contracts,
        core_data=data,
    )
    (tmp / "api" / "qg-cockpit.json").write_text(
        json.dumps(qg_cockpit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    pages = [
        ("/manifeste/",   "manifeste",   "Manifeste",               page_manifeste(manifeste)),
        ("/docs/",        "docs",        "Docs",                    page_docs(docs_index)),
        ("/carte/",       "carte",       "Carte du puzzle",         page_carte(carte_payload)),
        ("/",             "registry",    "Registry CORE OA",        page_registry(data, pending_alex_actions, builds_today, objectifs, builds, agent_loop_audit, blocages_payload, vps_fleet, agent_activity)),
        ("/cockpit/",     "cockpit",     "Cockpit décisions/proofs/agents", page_qg_cockpit(qg_cockpit)),
        ("/productivite/", "productivite", "Objectif du jour",       page_productivite(productivite, ledger)),
        ("/blocages/",    "blocages",    "Blocages",                page_blocages(blocages_payload)),
        ("/objectifs/",   "objectifs",   "Objectifs",               page_objectifs(objectifs, decisions)),
        ("/chantiers/",   "chantiers",   "Chantiers",               page_chantiers(chantiers)),
        ("/agent-loop/",  "agent-loop",  "Audit anti-orphelins",     page_agent_loop_audit(agent_loop_audit, agent_loop_registry)),
        ("/agent-activity/", "agent-activity", "Activité agents",     page_agent_activity(agent_activity)),
        ("/ops/",         "ops",         "Ops quotidien",           page_ops(ledger, repo_health, storage, vps_fleet, hub_node_maturity)),
        ("/controle-oa/", "controle-oa", "Contrôle OA",             page_oa_system_control(oa_system_contracts)),
        ("/clients/",     "clients",     "Clients & VPS",           page_clients(data)),
        ("/decisions/",   "decisions",   "Décisions",                page_decisions(decisions)),
        ("/builds/",      "builds",      "Builds du jour",           page_builds(builds)),
        ("/partenaires/", "partenaires", "Partenaires",              page_partenaires(data)),
        ("/changelog/",   "changelog",   "Changelog",                page_changelog()),
    ]
    for app in data.get("items", []):
        app_route = _app_route(app)
        app_active = {
            "/apps/qg/": "app-qg",
            "/apps/hub/": "app-hub",
            "/apps/app/": "app-app",
            "/apps/omartop/": "app-omartop",
            "/apps/landing/": "app-landing",
            "/apps/catalogue/": "app-catalogue",
            "/apps/lab/": "app-lab",
        }.get(app_route, "registry")
        pages.append((app_route, app_active, f'{app.get("name", "App")} · fiche app', page_app_detail(data, app, builds, ledger_history)))
    for route, active, title, body in pages:
        out = tmp / "index.html" if route == "/" else tmp / route.strip("/") / "index.html"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(layout(active, title, built_at, body), encoding="utf-8")

    if out_root.exists():
        import shutil
        shutil.rmtree(out_root)
    tmp.rename(out_root)

    healthy = data["counts"]["healthy"]
    issues  = data["counts"]["open_issues_total"]
    prs     = data["counts"]["open_prs_total"]
    print(f"built qg {len(pages)} routes · {healthy}/{data['counts']['total']} healthy · {issues} issues · {prs} PRs · ledger {ledger['date']} · {built_at}")


if __name__ == "__main__":
    main()
