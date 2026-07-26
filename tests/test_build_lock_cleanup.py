import importlib.util
import fcntl
import os
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


def test_build_lock_path_uses_a_private_runtime_directory_outside_checkout(tmp_path, monkeypatch):
    mod = load_build()
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    fallback_parent = tmp_path / "runtime-parent"
    fallback_parent.mkdir()
    monkeypatch.setattr(mod, "ROOT", checkout)
    monkeypatch.delenv("XDG_RUNTIME_DIR", raising=False)
    monkeypatch.setattr(mod.tempfile, "gettempdir", lambda: str(fallback_parent))

    output = tmp_path / "staging" / "public"
    same_output_lock = mod.build_lock_path(output)
    assert same_output_lock == mod.build_lock_path(output)
    assert same_output_lock != mod.build_lock_path(tmp_path / "other-staging" / "public")
    assert not same_output_lock.is_relative_to(checkout)
    assert same_output_lock.parent.name == f"oa-qg-build-locks-{os.getuid()}"
    assert same_output_lock.parent.stat().st_mode & 0o077 == 0

    xdg_runtime = tmp_path / "xdg-runtime"
    xdg_runtime.mkdir(mode=0o700)
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(xdg_runtime))
    assert mod.build_lock_path(output).parent == xdg_runtime / "oa-qg-build-locks"


def test_main_releases_lock_fd_on_error_without_polluting_checkout(tmp_path, monkeypatch):
    mod = load_build()
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    runtime = tmp_path / "runtime"
    runtime.mkdir(mode=0o700)
    out_root = tmp_path / "staging" / "public"
    monkeypatch.setattr(mod, "ROOT", checkout)
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(runtime))
    monkeypatch.setenv("QG_BUILD_OUTPUT_DIR", str(out_root))

    lock_path = mod.build_lock_path(out_root)

    with pytest.raises(SystemExit, match="--client=<id>"):
        mod.main(["--view=client"])

    fd = os.open(lock_path, os.O_RDWR)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    finally:
        os.close(fd)
    assert list(checkout.iterdir()) == []
