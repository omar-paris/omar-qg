import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load_feedback():
    spec = importlib.util.spec_from_file_location(
        "collect_feedback_alex_test", ROOT / "scripts" / "collect_feedback_alex.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_feedback_alex_dry_run_creates_local_triage_candidate(tmp_path, monkeypatch):
    m = _load_feedback()
    monkeypatch.setattr(m, "VAR", tmp_path)
    monkeypatch.setattr(m, "LOG", tmp_path / "feedback-alex-local.log")
    monkeypatch.setattr(m, "STATE", tmp_path / "feedback-alex-seen.json")

    event = m.maybe_collect(
        "t_1234abcd",
        "??? je fais quoi, où est le lien ? impossible d'agir",
        source="test:/blocages",
        mode="dry-run",
    )

    assert event["action"] == "dry_run"
    assert event["ref"] == "t_1234abcd"
    assert "question_marks" in event["reasons"]
    assert "missing_link_or_action" in event["reasons"]
    assert event["title"].startswith("[FEEDBACK-ALEX]")
    assert event["idempotency_key"].startswith("feedback-alex:")
    assert "pas de notification groupe" in event["body_preview"]
    assert (tmp_path / "feedback-alex-local.log").exists()
    seen = json.loads((tmp_path / "feedback-alex-seen.json").read_text(encoding="utf-8"))
    assert len(seen) == 1

    duplicate = m.maybe_collect(
        "t_1234abcd",
        "??? je fais quoi, où est le lien ? impossible d'agir",
        source="test:/blocages",
        mode="dry-run",
    )
    assert duplicate["action"] == "duplicate"


def test_feedback_alex_neutral_answer_does_not_create(tmp_path, monkeypatch):
    m = _load_feedback()
    monkeypatch.setattr(m, "VAR", tmp_path)
    monkeypatch.setattr(m, "LOG", tmp_path / "feedback-alex-local.log")
    monkeypatch.setattr(m, "STATE", tmp_path / "feedback-alex-seen.json")

    event = m.maybe_collect("t_1234abcd", "FAIT", source="test:/blocages", mode="dry-run")

    assert event["action"] == "ignored"
    assert event["reasons"] == []
    assert not (tmp_path / "feedback-alex-local.log").exists()
    assert not (tmp_path / "feedback-alex-seen.json").exists()


def test_feedback_alex_create_mode_uses_triage_kanban_without_group_notification(tmp_path, monkeypatch):
    m = _load_feedback()
    monkeypatch.setattr(m, "VAR", tmp_path)
    monkeypatch.setattr(m, "LOG", tmp_path / "feedback-alex-local.log")
    monkeypatch.setattr(m, "STATE", tmp_path / "feedback-alex-seen.json")
    monkeypatch.setattr(m, "HERMES", "/bin/hermes-test")
    monkeypatch.setattr(m, "ASSIGNEE", "default")
    calls = []

    class Proc:
        returncode = 0
        stdout = '{"id":"t_feedback"}'
        stderr = ""

    def fake_run(cmd, **kwargs):
        calls.append((cmd, kwargs))
        return Proc()

    monkeypatch.setattr(m.subprocess, "run", fake_run)

    event = m.maybe_collect("omar-qg#27", "ça marche pas, quel lien ?", source="test:/blocages", mode="create")

    assert event["action"] == "created"
    cmd = calls[0][0]
    assert cmd[:3] == ["/bin/hermes-test", "kanban", "create"]
    assert "--triage" in cmd
    assert "--idempotency-key" in cmd
    assert "--created-by" in cmd and "oa-secretaire" in cmd
    assert "--assignee" in cmd and "default" in cmd
    body = cmd[cmd.index("--body") + 1]
    assert "pas de notification groupe automatique" in body
    assert "Extrait court redacted" in body
