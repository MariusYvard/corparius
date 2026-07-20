"""The settings resolver. What matters here is the order of the layers and the
fact that it is reportable: a value the operator cannot change from the console
must be visible as such, never silently ignored."""

import pytest

from corparius import cfg
from corparius.config import Settings
from corparius.store import Store


@pytest.fixture()
def layers(tmp_path, monkeypatch):
    """A .env file and a store, both empty, wired to the resolver."""
    env_file = tmp_path / ".env"
    env_file.write_text("CORP_TRIVIAL_MODEL=local:from-dotenv\n", encoding="utf-8")
    cfg.set_dotenv_path(env_file)
    monkeypatch.setenv("CORP_DATA_PATH", str(tmp_path))
    cfg.invalidate()
    return {"env_file": env_file, "store": Store(str(tmp_path))}


def test_dotenv_is_read_but_never_leaks_into_os_environ(layers, monkeypatch):
    import os

    monkeypatch.delenv("CORP_TRIVIAL_MODEL", raising=False)
    assert cfg.get("CORP_TRIVIAL_MODEL") == "local:from-dotenv"
    # The whole layering depends on this: if .env landed in os.environ it would
    # become layer 1 and outrank the console for good.
    assert "CORP_TRIVIAL_MODEL" not in os.environ
    assert cfg.source("CORP_TRIVIAL_MODEL") == "dotenv"


def test_precedence_env_over_store_over_dotenv_over_default(layers, monkeypatch):
    monkeypatch.delenv("CORP_TRIVIAL_MODEL", raising=False)
    assert cfg.get("CORP_TRIVIAL_MODEL", "d") == "local:from-dotenv"

    layers["store"].set_setting("CORP_TRIVIAL_MODEL", "local:from-console")
    cfg.invalidate()
    assert cfg.get("CORP_TRIVIAL_MODEL", "d") == "local:from-console"
    assert cfg.source("CORP_TRIVIAL_MODEL") == "db"

    monkeypatch.setenv("CORP_TRIVIAL_MODEL", "local:from-shell")
    assert cfg.get("CORP_TRIVIAL_MODEL", "d") == "local:from-shell"
    assert cfg.source("CORP_TRIVIAL_MODEL") == "env"

    assert cfg.get("CORP_NOT_SET_ANYWHERE", "d") == "d"
    assert cfg.source("CORP_NOT_SET_ANYWHERE") == "default"


def test_bootstrap_keys_ignore_the_store(layers, monkeypatch):
    """You cannot ask the database where the database is."""
    monkeypatch.delenv("CORP_UI_PORT", raising=False)
    layers["store"].set_setting("CORP_UI_PORT", "9999")
    cfg.invalidate()
    assert cfg.get("CORP_UI_PORT", "8600") == "8600"
    assert cfg.source("CORP_UI_PORT") == "default"


def test_settings_reresolves_per_instance(layers, monkeypatch):
    """The bug that made the console look like it worked: Settings() used to
    freeze every field at import, so a second instance handed back stale values."""
    monkeypatch.setenv("CORP_LLM_MOCK", "true")
    assert Settings().llm_mock is True
    monkeypatch.setenv("CORP_LLM_MOCK", "false")
    assert Settings().llm_mock is False


def test_store_writes_are_visible_without_restarting(layers):
    """The console writes through one connection and cfg reads through another,
    so the read-only view has to notice the commit."""
    assert cfg.get("CORP_HARD_MODEL", "d") == "d"
    layers["store"].set_setting("CORP_HARD_MODEL", "groq:big")
    assert cfg.get("CORP_HARD_MODEL", "d") == "groq:big"


def test_missing_store_and_missing_dotenv_are_just_empty_layers(tmp_path, monkeypatch):
    monkeypatch.setenv("CORP_DATA_PATH", str(tmp_path / "nothing-here"))
    cfg.set_dotenv_path(tmp_path / "absent.env")
    cfg.invalidate()
    assert cfg.get("CORP_HARD_MODEL", "fallback") == "fallback"
    # Reading configuration must not create the data directory: corparius.config
    # builds a Settings() at import time.
    assert not (tmp_path / "nothing-here").exists()


def test_parse_dotenv_tolerates_real_files():
    parsed = cfg.parse_dotenv(
        "# a comment\n"
        "\n"
        "PLAIN=value\n"
        "  SPACED = spaced value \n"
        'QUOTED="quoted"\n'
        "SINGLE='single'\n"
        "export EXPORTED=exported\n"
        "EMPTY=\n"
        "no_equals_sign\n"
        "URL=https://example.com/a?b=c\n"
    )
    assert parsed == {
        "PLAIN": "value",
        "SPACED": "spaced value",
        "QUOTED": "quoted",
        "SINGLE": "single",
        "EXPORTED": "exported",
        "EMPTY": "",
        "URL": "https://example.com/a?b=c",
    }
