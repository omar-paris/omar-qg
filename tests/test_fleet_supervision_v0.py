from pathlib import Path
import json
import os
import subprocess

ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / "public"


def test_qg_publishes_fleet_supervision_v0_api():
    subprocess.run(
        ["python3", "scripts/build.py"],
        cwd=ROOT,
        check=True,
        env={**os.environ, "QG_USE_TEST_FIXTURES": "1"},
    )
    fleet_path = PUBLIC / "api" / "oa-fleet-supervision-v0.json"
    inventory_path = PUBLIC / "api" / "vps-app-inventory.json"
    assert fleet_path.exists()
    assert inventory_path.exists()

    fleet = json.loads(fleet_path.read_text(encoding="utf-8"))
    inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    assert fleet["schema"] == "oa.fleet-supervision.v0"
    assert inventory["schema"] == "oa.vps-app-inventory/1"

    fleet_nodes = {node["node"] for node in fleet["nodes"]}
    inventory_nodes = {node["node"] for node in inventory["nodes"]}
    assert {"oa-master", "jab", "pantheos"} <= fleet_nodes
    assert {"oa-master", "jab", "pantheos"} <= inventory_nodes
    assert fleet["totals"]["controls"] >= 15 * 3
    assert fleet["totals"]["apps"] >= 30

    clients_html = (PUBLIC / "clients" / "index.html").read_text(encoding="utf-8")
    assert "Clients — inventaire apps silencieux" in clients_html
    assert "Source de supervision unique" in clients_html
    assert "Supervision unique /ops/" in clients_html
    assert "Compat legacy V0" in clients_html
    assert "Standards OA · 3 VPS" not in clients_html
    assert "Standards OA — supervision 3 VPS" not in clients_html
    assert "Compat matrice V0 · non supervision" not in clients_html
    assert "API compat V0" not in clients_html
    assert "/api/oa-fleet-supervision-v0.json" not in clients_html
    assert "oa-master (alias omar)" in clients_html.lower()
    assert "ne crée pas un 4e VPS de supervision" in clients_html
    assert "pantheos" in clients_html.lower()
    assert "jab" in clients_html.lower()
    inventory_section = clients_html.split("Inventaire apps/version par VPS", 1)[1]
    assert "Standards OA · 3 VPS" not in inventory_section
    assert "Standards OA — supervision 3 VPS" not in inventory_section
