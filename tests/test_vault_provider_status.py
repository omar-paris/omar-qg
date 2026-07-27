import importlib.util
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_build():
    spec = importlib.util.spec_from_file_location("qg_build_vault_status", ROOT / "scripts" / "build.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_vault_enospc_is_not_reported_as_missing_hetzner_key(monkeypatch):
    mod = load_build()

    monkeypatch.setattr(
        mod.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args[0], 2, stdout="", stderr="audit sink write failed: no space left on device"
        ),
    )

    result = mod._vault_read(mod.HETZNER_VAULT_PATH)

    assert result.status == "vault_unavailable"
    assert result.data == {}
    assert mod.probe_hetzner() == "vault_unavailable"


def test_vault_missing_secret_remains_distinct_from_vault_failure(monkeypatch):
    mod = load_build()

    monkeypatch.setattr(
        mod.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args[0], 2, stdout="", stderr="No value found at secret/integrations/hetzner/test"
        ),
    )

    result = mod._vault_read(mod.HETZNER_VAULT_PATH)

    assert result.status == "secret_missing"
    assert result.data == {}
    assert mod.probe_hetzner() == "key_missing"


def test_hetzner_fleet_result_keeps_vault_failure_visible(monkeypatch):
    mod = load_build()

    monkeypatch.setattr(
        mod,
        "_vault_read",
        lambda path: mod.VaultReadResult(status="vault_unavailable", data={}),
    )

    result = mod.hetzner_fleet_result()

    assert result == {"items": [], "status": "vault_unavailable"}
