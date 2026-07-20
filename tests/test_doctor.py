"""The doctor must diagnose without crashing in every mode and say what to do."""

from app.config import Settings
from app.doctor import run_checks


def _s(tmp_path, **kw):
    s = Settings()
    s.data_path = str(tmp_path)
    for k, v in kw.items():
        setattr(s, k, v)
    return s


def test_mock_mode_is_green_without_network(tmp_path):
    results = run_checks(_s(tmp_path, llm_mock=True))
    by = {r["name"]: r for r in results}
    assert by["mode"]["level"] == "ok"
    assert by["store"]["level"] == "ok"
    assert by["network"]["level"] == "ok"  # not needed in mock
    assert by["ollama"]["level"] in ("ok", "warn")  # absent ollama only warns


def test_live_without_keys_warns_actionably(tmp_path, monkeypatch):
    for spec_env in (
        "GROQ_API_KEY",
        "ANTHROPIC_API_KEY",
        "CEREBRAS_API_KEY",
        "OPENROUTER_API_KEY",
        "MISTRAL_API_KEY",
    ):
        monkeypatch.delenv(spec_env, raising=False)
    results = run_checks(_s(tmp_path, llm_mock=False, cloud_enabled=True))
    by = {r["name"]: r for r in results}
    assert by["providers"]["level"] == "warn"
    assert "Groq" in by["providers"]["message"]


def test_claude_cli_check_fails_when_enabled_but_missing(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", "")
    results = run_checks(_s(tmp_path, claude_code_enabled=True))
    by = {r["name"]: r for r in results}
    assert by["claude cli"]["level"] == "fail"
