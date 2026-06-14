"""Garde-fou RBAC — isolation client (Standard 3).

Le coeur de la valeur : prouver que la vue client générée (Niveau 2) ne contient
QUE les ressources du client et JAMAIS un champ `internal_only`
(ip, price_eur, hetzner_id, tailnet...). Ce test ÉCHOUERAIT vraiment si on
fuitait un champ interne — la démonstration est faite par
test_guardrail_would_catch_a_leak.
"""
from pathlib import Path
import importlib.util
import json
import subprocess

ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / "public"
RBAC = ROOT / "rbac"

# Champs qui ne doivent JAMAIS apparaître dans une vue client, où qu'ils soient.
INTERNAL_ONLY = ["ip", "hetzner_id", "price_eur", "tailnet"]


def _load_build():
    spec = importlib.util.spec_from_file_location("qg_build", ROOT / "scripts" / "build.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _walk_strings(obj):
    """Tous les noms de clés et valeurs scalaires d'un objet JSON, à plat."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield str(k)
            yield from _walk_strings(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk_strings(v)
    else:
        yield str(obj)


# ── 1. Fichiers et schéma présents ────────────────────────────────────────────

def test_actors_yaml_present_and_well_formed():
    build = _load_build()
    actors = build.load_actors()
    assert actors, "rbac/actors.yaml doit définir des acteurs"
    assert actors["alex"]["role_default"] == "owner"
    assert actors["ccma"]["role_default"] == "operator"
    assert actors["h-omar"]["role_default"] == "operator"
    assert actors["jab"]["role_default"] == "client"
    assert actors["public"]["role_default"] == "public"


def test_access_schema_on_vps():
    build = _load_build()
    for key in ("omar", "pan", "jab"):
        access = build.VPS_META[key].get("access")
        assert access, f"VPS {key} doit porter un bloc access"
        assert "owner" in access and "viewers" in access
        assert "client_view" in access and "internal_only" in access
    jab = build.VPS_META["jab"]["access"]
    assert jab["owner"] == "jab"
    assert set(["alex", "ccma", "h-omar"]) <= set(jab["viewers"])
    assert jab["client_view"] == ["health", "services", "invoice"]
    assert set(INTERNAL_ONLY) <= set(jab["internal_only"])


# ── 2. La vue client n'expose que les bonnes ressources ───────────────────────

def test_client_view_only_own_resources():
    build = _load_build()
    view = build.build_client_view("jab")
    # jab est owner du seul VPS-JAB ; il ne voit pas VPS-Omar ni VPS-Pantheos
    labels = {r.get("label") for r in view["resources"]}
    assert labels == {"VPS-JAB"}, labels
    assert view["resource_count"] == 1


def test_client_view_only_client_view_fields():
    build = _load_build()
    view = build.build_client_view("jab")
    allowed = set(build.VPS_META["jab"]["access"]["client_view"])
    for r in view["resources"]:
        assert set(r.get("fields", {}).keys()) <= allowed


# ── 3. GARDE-FOU : aucun champ internal_only dans la vue client ───────────────

def test_no_internal_field_in_client_view():
    """Coeur de la valeur : isolation PROUVABLE. Échoue si un champ interne fuite."""
    build = _load_build()
    json_path = build.write_client_view("jab")
    view = json.loads(json_path.read_text(encoding="utf-8"))
    tokens = set(_walk_strings(view))
    for field in INTERNAL_ONLY:
        assert field not in tokens, f"FUITE: champ interne '{field}' dans la vue client jab"
    # Aussi : pas de valeurs typiquement sensibles (IP tailnet, symbole prix)
    blob = json.dumps(view, ensure_ascii=False)
    for sentinel in ("100.79.68.6", "hetzner.cloud/v1"):
        assert sentinel not in blob


def test_client_view_html_has_no_leak():
    build = _load_build()
    build.write_client_view("jab")
    html = (PUBLIC / "client" / "jab" / "index.html").read_text(encoding="utf-8")
    for field in INTERNAL_ONLY:
        assert f'>{field} :' not in html and f'"{field}"' not in html


# ── 4. DÉMONSTRATION : le garde-fou attraperait vraiment une fuite ────────────

def test_guardrail_would_catch_a_leak():
    """Si une ressource exposait un champ interne via client_view, le filtre
    devrait quand même le retirer (defense-in-depth via SENSITIVE_FIELDS).
    On le prouve en forçant ip/price_eur dans client_view + la ressource."""
    build = _load_build()
    leaky_resource = {
        "label": "VPS-EVIL",
        "name": "VPS-EVIL",
        "role": "CLIENT",
        "ip": "203.0.113.5",
        "price_eur": 42.0,
        "hetzner_id": 99999,
        "health": "ok",
    }
    # access mal configuré qui tente d'exposer des champs sensibles
    bad_access = {
        "owner": "jab",
        "viewers": [],
        "client_view": ["health", "ip", "price_eur", "hetzner_id"],
        "internal_only": [],
    }
    projected = build.filter_resource_for_client(leaky_resource, bad_access)
    out_fields = set(projected.get("fields", {}).keys())
    # Le filtre laisse passer health mais BLOQUE ip/price_eur/hetzner_id
    assert "health" in out_fields
    for sensitive in ("ip", "price_eur", "hetzner_id"):
        assert sensitive not in out_fields, f"defense-in-depth a laissé fuiter {sensitive}"
    # Et la valeur de l'IP n'apparaît nulle part dans la projection
    assert "203.0.113.5" not in json.dumps(projected)


def test_unknown_client_gets_empty_view():
    build = _load_build()
    view = build.build_client_view("inconnu")
    assert view["resource_count"] == 0


# ── 5. Rétrocompat : le CLI client ne casse pas, sortie présente ──────────────

def test_cli_client_view_generates_artifact(tmp_path):
    out = subprocess.run(
        ["python3", "scripts/build.py", "--view=client", "--client=jab"],
        cwd=ROOT, check=True, capture_output=True, text=True,
    )
    assert "built client view 'jab'" in out.stdout
    assert (PUBLIC / "api" / "client-jab.json").exists()
    assert (PUBLIC / "client" / "jab" / "index.html").exists()
