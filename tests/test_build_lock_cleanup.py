import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def load_build():
    spec = importlib.util.spec_from_file_location("qg_build_lock_test", ROOT / "scripts" / "build.py")
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_main_keeps_build_mutex_outside_checkout_and_releases_it_on_error(tmp_path, monkeypatch):
    mod = load_build()
    out_root = tmp_path / "public"
    checkout_lock_path = tmp_path / ".public.qg-build.lock"
    monkeypatch.setattr(mod, "ROOT", tmp_path)
    monkeypatch.setenv("QG_BUILD_OUTPUT_DIR", str(out_root))

    for _ in range(2):
        with pytest.raises(SystemExit, match="--client=<id>"):
            mod.main(["--view=client"])

    assert not checkout_lock_path.exists()
    assert len(list((tmp_path / "var" / "build-locks").glob("qg-build-*.lock"))) == 1
