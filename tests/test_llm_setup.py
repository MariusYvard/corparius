"""Plug in an LLM without a shell: test any provider, pull Ollama models, pick a
local server. Each is the same "prove it, don't trust it" the mail and Claude
setup got."""

import threading
import types

import pytest

from corparius import webui
from corparius.config import cfg
from corparius.config.settings import Settings
from corparius.kernel.records import LLMResult, Usage
from corparius.providers import ollama_setup, provider_check

from .test_webui import _call


@pytest.fixture()
def server(tmp_path, monkeypatch):
    monkeypatch.setenv("CORP_DATA_PATH", str(tmp_path))
    monkeypatch.delenv("CORP_UI_TOKEN", raising=False)
    cfg.set_dotenv_path(tmp_path / ".env")
    cfg.invalidate()
    srv = webui.build_server(Settings(), host="127.0.0.1", port=0, env_file=tmp_path / ".env")
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv
    srv.shutdown()
    srv.server_close()  # release the listening socket, not just the loop


# --- provider test button -------------------------------------------------
def test_provider_test_reports_a_working_key(server, monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "gsk_ok")
    monkeypatch.setattr(
        provider_check.OpenAICompatProvider,
        "generate",
        lambda self, m, model, max_tokens=8: LLMResult(
            text="ready", usage=Usage(1, 1), model=model, provider="groq"
        ),
    )
    cfg.invalidate()
    status, d = _call(server, "POST", "/api/test/provider", {"name": "groq"})
    assert status == 200 and d["result"]["ok"] and "works" in d["result"]["detail"]


def test_provider_test_names_the_fix_on_a_bad_key(server, monkeypatch):
    import requests

    monkeypatch.setenv("GROQ_API_KEY", "gsk_bad")
    resp = types.SimpleNamespace(status_code=401, text="invalid api key")

    def boom(self, m, model, max_tokens=8):
        raise requests.HTTPError(response=resp)

    monkeypatch.setattr(provider_check.OpenAICompatProvider, "generate", boom)
    cfg.invalidate()
    status, d = _call(server, "POST", "/api/test/provider", {"name": "groq"})
    assert d["result"]["ok"] is False and "rejected this key" in d["result"]["detail"]


def test_provider_test_says_when_no_key_is_set(server, monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    cfg.invalidate()
    status, d = _call(server, "POST", "/api/test/provider", {"name": "groq"})
    assert d["result"]["ok"] is False and d["result"]["configured"] is False


# --- ollama ---------------------------------------------------------------
def test_ollama_status_lists_missing_tier_models(server, monkeypatch):
    monkeypatch.setattr(ollama_setup, "wanted_models", lambda s=None: ["gemma", "qwen"])

    class Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"models": [{"name": "gemma:latest"}]}

    monkeypatch.setattr(ollama_setup.requests, "get", lambda *a, **k: Resp())
    status, d = _call(server, "GET", "/api/ollama")
    r = d["result"]
    assert r["reachable"] and r["present"] == ["gemma"] and r["missing"] == ["qwen"]


def test_ollama_unreachable_is_reported_not_a_crash(server, monkeypatch):
    import requests

    monkeypatch.setattr(ollama_setup, "wanted_models", lambda s=None: ["gemma"])

    def down(*a, **k):
        raise requests.ConnectionError("refused")

    monkeypatch.setattr(ollama_setup.requests, "get", down)
    status, d = _call(server, "GET", "/api/ollama")
    assert status == 200 and d["result"]["reachable"] is False
    assert "not reachable" in d["result"]["detail"]


def test_ollama_pull_runs_in_the_background_and_reports(server, monkeypatch):
    monkeypatch.setattr(
        ollama_setup,
        "status",
        lambda: {
            "ok": False,
            "reachable": True,
            "missing": ["gemma"],
            "present": [],
            "wanted": ["gemma"],
            "url": "x",
            "detail": "d",
        },
    )
    pulled = []

    def fake_pull(model, on_line=None, timeout=3600):
        pulled.append(model)
        if on_line:
            on_line(f"{model}: pulling")
        return {"ok": True, "detail": f"{model}: done"}

    monkeypatch.setattr(ollama_setup, "pull", fake_pull)
    status, d = _call(server, "POST", "/api/ollama/pull", {"models": ["gemma"]})
    assert status == 200 and d["ok"] and d["pulling"] == ["gemma"]
    # The worker is a background thread; give it a beat.
    import time

    for _ in range(50):
        if pulled:
            break
        time.sleep(0.05)
    assert pulled == ["gemma"]


# --- local server presets -------------------------------------------------
def test_server_presets_are_offered(server):
    status, d = _call(server, "GET", "/api/providers")
    ids = {p["id"] for p in d["server_presets"]}
    assert {"lmstudio", "jan", "vllm"} <= ids
    lm = next(p for p in d["server_presets"] if p["id"] == "lmstudio")
    assert lm["url"].startswith("http://localhost:1234")


# --- localized diagnosis ---------------------------------------------------
def test_diagnosis_answers_in_french(server, monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    from corparius.config import cfg

    cfg.invalidate()
    status, d = _call(server, "POST", "/api/test/provider", {"name": "groq", "lang": "fr"})
    assert "Aucune clé" in d["result"]["detail"]
    status, d = _call(server, "POST", "/api/test/provider", {"name": "groq", "lang": "en"})
    assert "No key" in d["result"]["detail"]


def test_ollama_status_localized(server, monkeypatch):
    import requests

    from corparius.providers import ollama_setup

    monkeypatch.setattr(ollama_setup, "wanted_models", lambda s=None: ["gemma"])
    monkeypatch.setattr(
        ollama_setup.requests,
        "get",
        lambda *a, **k: (_ for _ in ()).throw(requests.ConnectionError()),
    )
    status, d = _call(server, "GET", "/api/ollama?lang=fr")
    assert "injoignable" in d["result"]["detail"]


# --- the measured machine on the ollama card -------------------------------
def test_the_ollama_card_carries_the_cached_profile_and_lists_once(server, monkeypatch, tmp_path):
    """The card is polled while a pull runs. It already asks /api/tags for the
    installed models; asking again to learn their sizes would double the timeout
    exposure on exactly the endpoint that gets hammered."""
    from corparius.providers import hardware
    from corparius.store import Store

    calls = []

    class Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"models": [{"name": "gemma:2b", "size": 1_680_000_000}]}

    def counted(url, *a, **k):
        calls.append(url)
        return Resp()

    monkeypatch.setattr(ollama_setup, "wanted_models", lambda s=None: ["gemma:2b"])
    monkeypatch.setattr(ollama_setup.requests, "get", counted)
    Store(str(tmp_path)).save_machine(
        {"cores": 8, "ram_total": 17_000_000_000, "tokens_per_second": 2.2, "placement": "cpu"}
    )
    status, d = _call(server, "GET", "/api/ollama")
    assert status == 200
    assert d["result"]["machine"]["tokens_per_second"] == 2.2
    assert d["result"]["local_model"] == "" and "2.2 tokens/s" in d["result"]["local_reason"]
    assert len([c for c in calls if "/api/tags" in c]) == 1, calls
    assert hardware  # imported for the reader: this is its cache being read


def test_the_ollama_card_never_measures(server, monkeypatch):
    """A measurement is a real generation — 93 seconds to load the configured
    model on the machine this was written for. It happens on a button, never on
    a poll."""
    from corparius.providers import hardware

    def explode(*a, **k):
        raise AssertionError("the polled card measured")

    monkeypatch.setattr(hardware, "measure", explode)
    monkeypatch.setattr(ollama_setup, "wanted_models", lambda s=None: ["gemma:2b"])

    class Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"models": [{"name": "gemma:2b", "size": 1_680_000_000}]}

    monkeypatch.setattr(ollama_setup.requests, "get", lambda *a, **k: Resp())
    status, d = _call(server, "GET", "/api/ollama")
    assert status == 200


def test_the_bench_button_measures_and_caches(server, monkeypatch, tmp_path):
    from corparius.providers import hardware
    from corparius.store import Store

    monkeypatch.setattr(
        hardware, "installed_models", lambda **k: [{"name": "gemma:2b", "size": 1_680_000_000}]
    )
    monkeypatch.setattr(
        hardware,
        "measure",
        lambda model, **k: {
            "ok": True,
            "model": model,
            "tokens_per_second": 8.6,
            "load_seconds": 6.9,
            "placement": "cpu",
        },
    )
    status, d = _call(server, "POST", "/api/ollama/bench", {})
    assert status == 200 and d["result"]["ok"] and d["result"]["tokens_per_second"] == 8.6
    assert Store(str(tmp_path)).load_machine()["tokens_per_second"] == 8.6


def test_the_bench_button_says_so_when_there_is_nothing_to_measure(server, monkeypatch):
    from corparius.providers import hardware

    monkeypatch.setattr(hardware, "installed_models", lambda **k: [])
    status, d = _call(server, "POST", "/api/ollama/bench", {})
    assert status == 200 and d["result"]["ok"] is False


def test_a_failed_measurement_does_not_overwrite_the_cache(server, monkeypatch, tmp_path):
    """A refused connection is not a machine that got slower."""
    from corparius.providers import hardware
    from corparius.store import Store

    Store(str(tmp_path)).save_machine({"tokens_per_second": 8.6, "placement": "cpu", "model": "m"})
    monkeypatch.setattr(hardware, "installed_models", lambda **k: [{"name": "m", "size": 1}])
    monkeypatch.setattr(
        hardware, "measure", lambda model, **k: {"ok": False, "detail": "did not answer"}
    )
    _call(server, "POST", "/api/ollama/bench", {})
    assert Store(str(tmp_path)).load_machine()["tokens_per_second"] == 8.6
