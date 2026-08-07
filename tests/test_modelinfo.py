"""What a model is, as opposed to whether it answers.

Measured behaviour is the strongest evidence there is, and it says nothing about
whether a model is any good at strategy — which is exactly what the hard tier
needs to know. So: the provider's own catalogue for context, generation and
reasoning support, a parameter count read out of the name when nothing describes
it, and an operator's own score table when they have one.

No benchmark leaderboard is scraped. They exist and they are web products, not
versioned APIs, and a frozen copy of one in this repo would rot exactly as the
pinned `default_model` did — silently, which is the failure this project keeps
paying for.
"""

import json

import pytest
import requests

from corparius.providers import modelinfo


class _Answer:
    """A `requests.get` result carrying a fixed catalogue payload."""

    status_code = 200

    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


def test_a_parameter_count_is_read_out_of_the_name():
    assert modelinfo.size_b("llama-3.3-70b-versatile") == 70.0
    assert modelinfo.size_b("gpt-oss-120b") == 120.0
    assert modelinfo.size_b("nemotron-nano-9b-v2") == 9.0
    # The version number is not a size: llama-3.1-8b is 8B, not 3.1B.
    assert modelinfo.size_b("meta/llama-3.1-8b-instruct") == 8.0
    assert modelinfo.size_b("mistral-small-latest") == 0.0


def test_one_model_wearing_three_provider_names_is_one_key():
    """`groq:llama-3.3-70b-versatile`, openrouter's `meta-llama/...-instruct`
    and nvidia's `meta/...-instruct` are the same weights."""
    keys = {
        modelinfo._normalise("llama-3.3-70b-versatile"),
        modelinfo._normalise("meta-llama/llama-3.3-70b-instruct"),
        modelinfo._normalise("meta/llama-3.3-70b-instruct"),
    }
    assert len(keys) == 1


def test_the_free_suffix_does_not_make_a_different_model():
    assert modelinfo._normalise("openai/gpt-oss-20b:free") == modelinfo._normalise("gpt-oss-20b")


def test_a_model_nothing_describes_says_so_rather_than_guessing():
    """`mistral-small-latest` is an alias, not a version, so no catalogue
    matches it. Reporting `unknown` is the honest answer."""
    described = modelinfo.describe("mistral-small-latest", {})
    assert described["matched"] is False and described["source"] == modelinfo.UNKNOWN
    assert described["context"] == 0 and described["reasoning"] is False


def test_a_name_carrying_a_size_falls_back_to_estimated():
    described = modelinfo.describe("some-unlisted-30b", {})
    assert described["source"] == modelinfo.ESTIMATED and described["params_b"] == 30.0


def test_routing_never_fetches_the_catalogue(tmp_path, monkeypatch):
    """A routing decision must not depend on the network being up, nor spend a
    request every time somebody presses "use recommended routing". The first
    version fetched here, and a CLI unit test promptly made a live call to
    openrouter."""
    from corparius.store import Store

    monkeypatch.setattr(
        requests, "get", lambda *a, **k: pytest.fail("routing reached for the network")
    )
    store = Store(str(tmp_path))
    assert modelinfo.cached(store) == {}
    store.close()


def test_the_catalogue_is_cached_and_read_back_without_the_network(tmp_path, monkeypatch):
    from corparius.store import Store

    payload = {
        "data": [
            {
                "id": "meta-llama/llama-3.3-70b-instruct",
                "context_length": 131072,
                "created": 1733000000,
                "supported_parameters": ["reasoning", "structured_outputs", "tools"],
            }
        ]
    }
    monkeypatch.setattr(requests, "get", lambda *a, **k: _Answer(payload))
    store = Store(str(tmp_path))
    assert "llama3.370b" in modelinfo.refresh(store)

    monkeypatch.setattr(requests, "get", lambda *a, **k: pytest.fail("fetched a second time"))
    entry = modelinfo.describe("groq:llama-3.3-70b-versatile", modelinfo.cached(store))
    assert entry["matched"] and entry["reasoning"] and entry["context"] == 131072
    assert modelinfo.age_days(store) >= 0
    store.close()


def test_the_catalogue_does_not_live_among_the_operators_settings(tmp_path, monkeypatch):
    """400 KB of somebody else's catalogue appearing as a row among the
    operator's own configuration, and travelling into their backups, was wrong
    twice over. It has its own table."""
    from corparius.store import Store

    payload = {"data": [{"id": "a/b-7b", "context_length": 8192, "created": 1}]}
    monkeypatch.setattr(requests, "get", lambda *a, **k: _Answer(payload))
    store = Store(str(tmp_path))
    modelinfo.refresh(store)
    assert "CORP_MODEL_CATALOGUE" not in store.all_settings()
    assert store.model_catalogue()
    store.close()


def test_a_failed_fetch_keeps_what_was_already_known(tmp_path, monkeypatch):
    """One bad afternoon should not cost the routing layer everything it knew."""
    from corparius.store import Store

    store = Store(str(tmp_path))
    store.save_model_catalogue({"a7b": {"context": 8192, "created": 1.0, "params_b": 7.0}})

    def boom(*a, **k):
        raise requests.ConnectionError("no")

    monkeypatch.setattr(requests, "get", boom)
    assert "a7b" in modelinfo.refresh(store)
    store.close()


def test_an_operator_score_table_is_read_when_pointed_at(tmp_path, monkeypatch):
    """How somebody who trusts a particular leaderboard uses it, without this
    repo shipping a frozen copy of one."""
    from corparius.config import cfg

    path = tmp_path / "scores.json"
    path.write_text(
        json.dumps({"llama-3.3-70b-instruct": 82, "junk": "not a number"}), encoding="utf-8"
    )
    monkeypatch.setattr(cfg, "get", lambda k, d="": str(path) if k == "CORP_MODEL_SCORES" else d)
    scores = modelinfo.operator_scores()
    assert scores[modelinfo._normalise("llama-3.3-70b-versatile")] == 82.0
    assert "junk" not in scores, "a value that is not a number is skipped, not crashed on"


def test_a_missing_or_broken_score_file_is_not_an_error(tmp_path, monkeypatch):
    from corparius.config import cfg

    monkeypatch.setattr(cfg, "get", lambda k, d="": "/nowhere/at/all.json")
    assert modelinfo.operator_scores() == {}

    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    monkeypatch.setattr(cfg, "get", lambda k, d="": str(bad))
    assert modelinfo.operator_scores() == {}
