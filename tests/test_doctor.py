"""The doctor must diagnose without crashing in every mode and say what to do."""

from corparius.config import Settings
from corparius.doctor import run_checks


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


def test_routing_check_is_quiet_in_mock_mode(tmp_path):
    by = {r["name"]: r for r in run_checks(_s(tmp_path, llm_mock=True))}
    assert by["routing"]["level"] == "ok"
    assert "fix" not in by["routing"]


def test_routing_check_flags_an_incoherent_tier_with_a_fix(tmp_path, monkeypatch):
    """The trap: cloud on, but tiers still point at unconfigured providers. The
    check must warn and carry the one-click fix hint the console renders."""
    for env in ("GROQ_API_KEY", "ANTHROPIC_API_KEY", "CEREBRAS_API_KEY"):
        monkeypatch.delenv(env, raising=False)
    from corparius import cfg

    cfg.invalidate()
    s = _s(
        tmp_path,
        llm_mock=False,
        cloud_enabled=True,
        normal_model="groq:llama-3.3-70b-versatile",  # no GROQ_API_KEY set
        hard_model="cloud:claude-3-5-sonnet-20241022",  # no ANTHROPIC key
        trivial_model="local:gemma4:e4b",  # local is fine
    )
    routing = {r["name"]: r for r in run_checks(s)}["routing"]
    assert routing["level"] == "warn"
    assert routing["fix"] == "recommend_routing"
    assert "normal" in routing["message"] and "hard" in routing["message"]
    assert "trivial" not in routing["message"]  # local resolves, not flagged


def test_routing_check_is_green_when_every_tier_resolves(tmp_path, monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "gsk_x")
    from corparius import cfg

    cfg.invalidate()
    s = _s(
        tmp_path,
        llm_mock=False,
        cloud_enabled=True,
        trivial_model="groq:llama-3.3-70b-versatile",
        normal_model="groq:llama-3.3-70b-versatile",
        hard_model="local:gemma4:e4b",
    )
    routing = {r["name"]: r for r in run_checks(s)}["routing"]
    assert routing["level"] == "ok" and "fix" not in routing
