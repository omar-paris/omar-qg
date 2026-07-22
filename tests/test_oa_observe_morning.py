from pathlib import Path
import importlib.util


MODULE_PATH = Path(__file__).parents[1] / "scripts" / "format_oa_observe_brief.py"


def load_formatter():
    spec = importlib.util.spec_from_file_location("format_oa_observe_brief", MODULE_PATH)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_p1_alerts_never_become_global_no_critical_claim():
    formatter = load_formatter()
    brief = """# Observation\nBilan : 0 P0 · 4 P1 · 0 P2\n\n### [P1] Swap sous pression · VPS-Omar\n"""

    message = formatter.format_brief(brief, "/tmp/brief.md")

    assert "Aucun point critique aujourd'hui" not in message
    assert "Aucun P0 détecté dans ce scan" in message
    assert "4 P1" in message
    assert "ne vaut pas état global" in message


def test_zero_alert_scan_is_explicitly_partial():
    formatter = load_formatter()
    message = formatter.format_brief(
        "Bilan : 0 P0 · 0 P1 · 2 P2\n", "/tmp/brief.md"
    )

    assert "Aucun point critique aujourd'hui" not in message
    assert "Aucun P0/P1 détecté dans ce scan partiel" in message
    assert "ne vaut pas état global" in message


def test_unparseable_bilan_fails_closed():
    formatter = load_formatter()
    message = formatter.format_brief("Bilan indisponible\n", "/tmp/brief.md")

    assert "Bilan P0/P1 illisible" in message
    assert "verdict global interdit" in message
    assert "Aucun point critique aujourd'hui" not in message
    assert "ne vaut pas état global" in message


def test_positive_p0_remains_scoped_to_scan():
    formatter = load_formatter()
    message = formatter.format_brief(
        "Bilan : 2 P0 · 0 P1 · 0 P2\n\n### [P0] Service indisponible · VPS-Omar\n",
        "/tmp/brief.md",
    )

    assert "2 P0 détecté(s) dans ce scan" in message
    assert "Service indisponible" in message
    assert "ne vaut pas état global" in message


def test_morning_wrapper_delegates_to_testable_formatter():
    wrapper = (MODULE_PATH.parent / "oa-observe-morning.sh").read_text(encoding="utf-8")

    assert 'scripts/format_oa_observe_brief.py "$BRIEF"' in wrapper
    assert "Aucun point critique aujourd'hui" not in wrapper
