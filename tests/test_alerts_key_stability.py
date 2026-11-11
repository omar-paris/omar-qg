"""Anti-récidive cartes dupliquées oa-alerts (incident 2026-11-11).

Trois cartes Kanban ont été créées pour la MÊME panne disque Pantheos
(t_7612ab9b « 78% », t_040e3a67 « 79% », puis état « 91% ») parce que la clé
d'anomalie contenait le pourcentage mesuré. Chaque variation d'un point
produisait une nouvelle clé -> nouvelle carte + nouveau Telegram, et un faux
« 🟢 résolu » à chaque changement.
"""
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_alerts():
    spec = importlib.util.spec_from_file_location("qg_alerts_keys", ROOT / "scripts" / "alerts.py")
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_stable_key_collapses_volatile_percentages():
    mod = load_alerts()
    assert mod.stable_key("vps-vps-pantheos-disque 78% (>70%)") == \
        mod.stable_key("vps-vps-pantheos-disque 91% (>70%)")
    assert mod.stable_key("disque 79% (>70%)") == "disque N% (>N%)"


def test_stable_key_keeps_distinct_anomalies_distinct():
    mod = load_alerts()
    assert mod.stable_key("vps-vps-omar-disque 79%") != mod.stable_key("vps-vps-pantheos-disque 79%")
    assert mod.stable_key("service nginx: failed") != mod.stable_key("service docker: failed")


def test_percentage_drift_is_not_a_new_alert_and_not_a_false_resolution():
    mod = load_alerts()
    prev = {"vps-vps-pantheos-disque 91% (>70%)": "vps-pantheos : disque 91% (>70%)"}
    cur = {"vps-vps-pantheos-disque N% (>N%)": "vps-pantheos : disque 79% (>70%)"}
    new, gone = mod.diff_alerts(prev, cur)
    assert new == {}, "une variation de pourcentage ne doit pas créer de carte"
    assert gone == {}, "une variation de pourcentage ne doit pas annoncer « résolu »"


def test_real_resolution_still_reported():
    mod = load_alerts()
    prev = {"vps-vps-pantheos-disque 79% (>70%)": "vps-pantheos : disque 79% (>70%)"}
    cur = {}
    new, gone = mod.diff_alerts(prev, cur)
    assert new == {}
    assert list(gone) == ["vps-vps-pantheos-disque 79% (>70%)"]


def test_real_new_anomaly_still_reported():
    mod = load_alerts()
    prev = {"health-app": "app.omar.paris ne répond pas (health 502)"}
    cur = {
        "health-app": "app.omar.paris ne répond pas (health 502)",
        "vps-vps-pantheos-disque N% (>N%)": "vps-pantheos : disque 82% (>70%)",
    }
    new, gone = mod.diff_alerts(prev, cur)
    assert list(new) == ["vps-vps-pantheos-disque N% (>N%)"]
    assert gone == {}
