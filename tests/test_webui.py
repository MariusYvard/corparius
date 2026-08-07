"""The operator console must serve the page, expose company state as JSON,
apply decisions, guard mutations with the optional token and never leak keys."""

import json
import logging
import os
import shutil
import threading
import time
from http.client import HTTPConnection

import pytest

from corparius import webui
from corparius.config import cfg
from corparius.config.settings import Settings
from corparius.kernel.records import ApprovalRequest

from .conftest import EXAMPLE_COMPANY


@pytest.fixture()
def server(tmp_path, monkeypatch):
    # Set the environment, not the instance: the console rebuilds Settings per
    # request (_fresh_settings) and cfg resolves the store path on its own, so
    # an attribute set here would only hold for this one object.
    monkeypatch.setenv("CORP_DATA_PATH", str(tmp_path))
    monkeypatch.setenv("CORP_LLM_MOCK", "true")
    monkeypatch.delenv("CORP_UI_TOKEN", raising=False)
    # This fixture runs real ticks against `example`, and an agent tool that saves
    # a company config would otherwise save the checkout's own — which it did,
    # stripping the comments and the `site:` block out of a tracked file. So the
    # example is copied into a private home and these tests write to the copy.
    home = tmp_path / "home"
    shutil.copytree(EXAMPLE_COMPANY, home / "companies" / "example")
    monkeypatch.setenv("CORP_HOME", str(home))
    cfg.invalidate()
    settings = Settings()
    srv = webui.build_server(settings, host="127.0.0.1", port=0, env_file=tmp_path / ".env")
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv
    srv.shutdown()
    srv.server_close()  # release the listening socket, not just the loop


def _call(srv, method, path, body=None, headers=None):
    conn = HTTPConnection("127.0.0.1", srv.socket.getsockname()[1], timeout=5)
    conn.request(
        method,
        path,
        json.dumps(body) if body is not None else None,
        {"Content-Type": "application/json", **(headers or {})},
    )
    res = conn.getresponse()
    data = (
        json.loads(res.read() or b"{}")
        if "json" in res.getheader("Content-Type", "")
        else res.read()
    )
    conn.close()
    return res.status, data


def test_serves_page_and_companies(server):
    status, page = _call(server, "GET", "/")
    assert status == 200 and b"corparius console" in page
    status, data = _call(server, "GET", "/api/companies")
    assert status == 200 and "example" in data["companies"]


def test_shutdown_drains_a_loop_run_before_closing_the_store(server, caplog):
    """On shutdown a continuous run must be stopped and allowed to unwind before
    the store closes; otherwise the day-boundary save_state() lands on a closed
    connection and logs a traceback. The drain path is what prevents that."""
    status, data = _call(
        server, "POST", "/api/run", {"company": "example", "ticks": 4, "loop": True}
    )
    assert status == 200 and data["ok"]
    time.sleep(0.4)  # let the worker enter its loop
    state = server.RequestHandlerClass.state
    assert any(r.get("stop") for r in state.runs.values()), "no run was active to drain"
    with caplog.at_level(logging.ERROR):
        webui._drain_and_close(state)
    assert "closed database" not in caplog.text.lower()
    assert state._store is None  # closed and cleared
    assert not any(
        t.name.startswith("corparius-run-") and t.is_alive() for t in threading.enumerate()
    )


def test_theme_persists_across_requests(server):
    # Empty by default; the page falls back to the code default.
    status, data = _call(server, "GET", "/api/theme")
    assert status == 200 and data["ok"] and "hue" not in data
    # Saving is what makes the theme follow the operator to another browser.
    status, data = _call(
        server, "POST", "/api/theme", {"hue": "160", "chroma": "1.2", "mode": "light"}
    )
    assert (
        status == 200
        and data["hue"] == "160"
        and data["chroma"] == "1.2"
        and data["mode"] == "light"
    )
    status, data = _call(server, "GET", "/api/theme")  # a fresh "device"
    assert data["hue"] == "160" and data["chroma"] == "1.2" and data["mode"] == "light"


def test_theme_validates_and_clears(server):
    _call(server, "POST", "/api/theme", {"hue": "999", "mode": "purple"})  # out of range / invalid
    _, data = _call(server, "GET", "/api/theme")
    assert "hue" not in data and "mode" not in data
    _call(server, "POST", "/api/theme", {"hue": "200"})
    _call(server, "POST", "/api/theme", {"hue": None})  # clear
    _, data = _call(server, "GET", "/api/theme")
    assert "hue" not in data


def test_overview_reads_store_and_decides_approval(server):
    store = server.RequestHandlerClass.state.store()
    store.add_approval(
        ApprovalRequest(
            id="ap1",
            company="example",
            agent="finance",
            tool="send_financial_transaction",
            parameters={"amount": 10},
        )
    )
    store.add_task("example", "Ship the landing page", "design", status="proposed")
    status, data = _call(server, "GET", "/api/overview?company=example")
    assert status == 200 and data["ok"]
    assert len(data["approvals"]) == 1
    assert data["tasks"]["proposed"][0]["title"] == "Ship the landing page"
    status, data = _call(
        server, "POST", "/api/approvals", {"id": "ap1", "decision": "approved", "note": "t"}
    )
    assert status == 200 and data["ok"]
    assert server.RequestHandlerClass.state.store().list_approvals("example", "pending") == []


def test_task_decision_updates_status(server):
    state = server.RequestHandlerClass.state
    state.store().add_task("example", "Draft outreach", "outreach", status="proposed")
    task_id = state.store().list_tasks("example", "proposed")[0]["id"]
    status, data = _call(server, "POST", "/api/tasks", {"id": task_id, "decision": "approved"})
    assert status == 200 and data["ok"]
    assert state.store().list_tasks("example", "approved")[0]["id"] == task_id


def test_providers_never_leak_keys_and_persist_env(server, monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "gsk_secret_value")
    status, data = _call(server, "GET", "/api/providers")
    assert status == 200
    groq = next(p for p in data["providers"] if p["name"] == "groq")
    assert groq["configured"] and groq["key_set"]
    assert "gsk_secret_value" not in json.dumps(data)
    # Keys are stored in the settings table, not in .env and not in os.environ:
    # .env is the layer below, and writing the process environment would make a
    # console value outrank every later edit. See corparius/cfg.py.
    status, data = _call(
        server, "POST", "/api/providers", {"values": {"CEREBRAS_API_KEY": "csk_new"}}
    )
    assert status == 200 and data["ok"]
    assert server.RequestHandlerClass.state.store().get_setting("CEREBRAS_API_KEY") == "csk_new"
    assert "CEREBRAS_API_KEY" not in os.environ
    assert "csk_new" not in json.dumps(data)
    cerebras = next(p for p in data["providers"] if p["name"] == "cerebras")
    assert cerebras["configured"] and cerebras["key_set"]
    status, data = _call(server, "POST", "/api/providers", {"values": {"PATH": "evil"}})
    assert status == 500 or data["ok"] is False


def test_saved_key_survives_a_restart_and_env_still_wins(server, tmp_path, monkeypatch):
    """The bug this whole layering exists to fix: a key saved from the page used
    to live only in os.environ and in a .env nobody read, so it vanished on the
    next start."""
    _call(server, "POST", "/api/providers", {"values": {"MISTRAL_API_KEY": "sk_kept"}})
    assert cfg.get("MISTRAL_API_KEY") == "sk_kept"
    cfg.invalidate()  # as if the process had just started again
    assert cfg.get("MISTRAL_API_KEY") == "sk_kept"
    assert cfg.source("MISTRAL_API_KEY") == "db"
    # An explicit process variable still outranks the console, and says so.
    monkeypatch.setenv("MISTRAL_API_KEY", "sk_from_shell")
    assert cfg.get("MISTRAL_API_KEY") == "sk_from_shell"
    assert cfg.source("MISTRAL_API_KEY") == "env"


def test_token_guards_reads_and_mutations(server, monkeypatch):
    """Reads used to stay open even with a token set. That was defensible while
    nothing but localhost could reach the port, but setting a token is the
    operator declaring the console reachable by someone they do not trust - and
    at that point /api/overview and /api/settings leaking company data, saved
    provider names and filesystem paths is not a defensible default."""
    monkeypatch.setenv("CORP_UI_TOKEN", "s3cret")
    status, data = _call(server, "POST", "/api/tasks", {"id": 1, "decision": "approved"})
    assert status == 401
    status, _ = _call(server, "GET", "/api/overview?company=example")
    assert status == 401
    status, _ = _call(
        server, "GET", "/api/overview?company=example", headers={"X-Corp-Token": "s3cret"}
    )
    assert status == 200
    status, data = _call(
        server,
        "POST",
        "/api/chat",
        {"company": "example", "message": "hi"},
        headers={"X-Corp-Token": "s3cret"},
    )
    assert status == 200 and data["ok"]


def test_reads_stay_open_when_no_token_is_configured(server):
    """The zero-config first run is untouched: with no CORP_UI_TOKEN there is
    no prompt, no login screen, and nothing to configure before the console
    works. The conftest fixture clears the variable, so this is that case."""
    status, _ = _call(server, "GET", "/api/overview?company=example")
    assert status == 200
    status, _ = _call(server, "POST", "/api/chat", {"company": "example", "message": "hi"})
    assert status == 200


def test_ceo_chat_answers_offline_in_mock_mode(server):
    # The chat now runs through the structured harness (so the CEO can propose
    # actions), but it must still answer offline in mock mode: a non-empty reply,
    # the mock provider, history that grows, and no action proposed on its own.
    status, data = _call(
        server, "POST", "/api/chat", {"company": "example", "message": "What is the plan?"}
    )
    assert status == 200 and data["ok"]
    assert data["provider"] == "mock"
    assert data["reply"] and data["proposal"] is None
    status, data = _call(server, "GET", "/api/chat?company=example")
    assert len(data["history"]) == 2


def test_doctor_endpoint_reports_checks(server):
    status, data = _call(server, "GET", "/api/doctor")
    assert status == 200 and data["ok"]
    names = {c["name"] for c in data["checks"]}
    assert {"python", "mode", "store", "ollama"} <= names
    assert all(c["level"] in ("ok", "warn", "fail") for c in data["checks"])


def test_company_wizard_creates_and_lists(server, tmp_path, monkeypatch):
    # corparius/company.py owns where a company lives now, so that the CLI, the
    # console and the MCP server cannot disagree about it — and it resolves that
    # place through paths.companies_dir() on every call, so CORP_HOME is the lever
    # rather than a module attribute this test used to reach in and rewrite.
    # paths.user_home() reads the environment directly, so there is no cache to
    # invalidate here — and `cfg` is a local further down this test anyway.
    monkeypatch.setenv("CORP_HOME", str(tmp_path))
    (tmp_path / "companies").mkdir()
    status, data = _call(
        server,
        "POST",
        "/api/companies",
        {
            "name": "Atelier Brumaire",
            "product": "Handmade candles online",
            "agents": {"coder": True},
            "session_tokens": 50000,
        },
    )
    assert status == 200 and data["ok"] and data["slug"] == "atelier-brumaire"
    import yaml as yaml_mod

    cfg = yaml_mod.safe_load(
        (tmp_path / "companies" / "atelier-brumaire" / "company.yaml").read_text(encoding="utf-8")
    )
    assert cfg["agents"]["coder"] is True and cfg["budgets"]["session_tokens"] == 50000
    # The wizard fills every field through the shared validator, so the editor
    # never opens a company with pieces missing.
    assert set(cfg) == {
        "slug",
        "name",
        "language",
        "one_liner",
        "offer",
        "icp",
        "agents",
        "budgets",
        "hitl_tools",
    }
    # Guessed from what the operator typed and written down, so they can see the
    # guess and correct it. This wizard was filled in English.
    assert cfg["language"] == "en"
    assert cfg["offer"]["billing"] == "stripe" and cfg["icp"]["channels"] == ["linkedin"]
    status, data = _call(
        server, "POST", "/api/companies", {"name": "Atelier Brumaire", "product": "dup"}
    )
    assert data["ok"] is False
    status, data = _call(server, "POST", "/api/companies", {"name": "!!!", "product": "x"})
    assert data["ok"] is False


def test_site_generate_and_serve(server):
    status, data = _call(server, "GET", "/api/site?company=example")
    assert status == 200 and data["built"] is False
    status, data = _call(server, "POST", "/api/site", {"company": "example"})
    assert status == 200 and data["ok"]
    status, page = _call(server, "GET", "/site/example/")
    assert status == 200 and b"<html" in page.lower()
    status, _ = _call(server, "GET", "/site/does-not-exist/")
    assert status == 404


def test_payments_mock_when_no_key(server, monkeypatch):
    monkeypatch.delenv("STRIPE_API_KEY", raising=False)
    status, data = _call(server, "GET", "/api/payments")
    assert status == 200 and data["source"] == "mock"
    assert data["total_paid"] > 0 and len(data["payments"]) >= 1


def test_unexpected_error_is_humanized_not_a_traceback(server, monkeypatch):
    # Force an unexpected failure inside a handler and confirm the operator gets a
    # sentence, not str(exc) or a traceback. The detail stays in the server log.
    import corparius.webui as webui_mod

    def boom(*a, **k):
        raise RuntimeError("secret internal detail xyzzy")

    monkeypatch.setattr(webui_mod, "_overview", boom)
    status, data = _call(server, "GET", "/api/overview?company=example")
    assert status == 500 and data["ok"] is False
    assert "xyzzy" not in data["error"]  # internals do not leak
    assert "server log" in data["error"]
    # Localized when the request says so.
    status, data = _call(server, "GET", "/api/overview?company=example&lang=fr")
    assert "journal du serveur" in data["error"]


# --- the console's two translation tables ----------------------------------
def _i18n_tables() -> tuple[set, set]:
    import re
    from pathlib import Path

    page = Path("corparius/webui.html").read_text(encoding="utf-8")
    block = page[page.index("const I18N = {") : page.index("const urlq =")]
    english, french = block[block.index("en:") : block.index("fr:")], block[block.index("fr:") :]
    # Three segments and hyphens both count. The pattern used to be two bare
    # segments, which quietly exempted every key the console reaches by building
    # its name — `dft.state.*`, `ib.fix.*`, `doc.why.*` — from the one test that
    # claims to guard translation parity.
    key = r"\"([a-zA-Z][\w.-]*\.[\w.-]+)\":"
    return set(re.findall(key, english)), set(re.findall(key, french))


def test_the_two_translation_tables_carry_the_same_keys():
    """`t()` falls back to English for a key French is missing, so a gap shows
    up as one English sentence in an otherwise French console — visible to the
    operator and to nobody running the tests."""
    english, french = _i18n_tables()
    assert english - french == set(), "missing from FR"
    assert french - english == set(), "missing from EN"
    assert len(english) > 300


def test_no_key_is_defined_twice_inside_one_table():
    """A JS object literal keeps the last of two identical keys and says nothing.

    `doc.` was the doctor's prefix and got reused for the documents card, so
    `doc.title` and `doc.desc` were each declared twice: both cards then rendered
    "Diagnostics", and the Documents tab carried the doctor's description. The
    parity test above compares the two tables to each other and was perfectly
    happy — the duplicate was in both languages. Only opening the page in a
    browser found it, which is not a test.
    """
    import re
    from pathlib import Path

    page = Path("corparius/webui.html").read_text(encoding="utf-8")
    block = page[page.index("const I18N = {") : page.index("const urlq =")]
    key = r"\"([a-zA-Z][\w.-]*\.[\w.-]+)\":"
    for name, table in (
        ("en", block[block.index("en:") : block.index("fr:")]),
        ("fr", block[block.index("fr:") :]),
    ):
        found = re.findall(key, table)
        dupes = sorted({k for k in found if found.count(k) > 1})
        assert not dupes, f"{name} declares these twice, and the last one wins: {dupes}"


def test_no_key_survives_the_thing_that_used_it():
    """prov.activate and toast.activated outlived their button by five days: the
    strings landed, the renderer never did. Four dead lines in both languages,
    and nothing said so.

    Only these two are pinned, not every key: several are reached through an
    expression (`t(ready ? "cc.reapply" : "cc.use")`), so a general sweep would
    call live keys dead.
    """
    from pathlib import Path

    page = Path("corparius/webui.html").read_text(encoding="utf-8")
    for gone in ("prov.activate", "toast.activated"):
        assert gone not in page, f"{gone} is back without a renderer"


# --- the update button -----------------------------------------------------
def test_the_polled_update_endpoint_says_whether_a_button_makes_sense(server, monkeypatch):
    """The page hides the button when the server cannot apply an update.
    Offering it from a source checkout would be a promise the next click
    breaks."""
    from corparius import selfupdate

    monkeypatch.setattr(selfupdate, "why_not", lambda: "")
    status, d = _call(server, "GET", "/api/update")
    assert status == 200 and d["can_apply"] is True
    monkeypatch.setattr(selfupdate, "why_not", lambda: "not the downloadable build")
    assert _call(server, "GET", "/api/update")[1]["can_apply"] is False


def test_applying_an_update_is_a_post_not_the_polled_get(server, monkeypatch):
    """It downloads tens of megabytes and then replaces the program. A poll
    must never be able to trigger that."""
    from corparius import selfupdate

    def explode(*a, **k):
        raise AssertionError("a GET applied an update")

    monkeypatch.setattr(selfupdate, "apply", explode)
    assert _call(server, "GET", "/api/update")[0] == 200


def test_an_update_is_refused_when_there_is_nothing_newer(server, monkeypatch):
    from corparius import selfupdate, update_check

    monkeypatch.setattr(
        update_check, "check", lambda *a, **k: {"enabled": True, "update_available": False}
    )

    def explode(*a, **k):
        raise AssertionError("downloaded a build we already run")

    monkeypatch.setattr(selfupdate, "apply", explode)
    status, d = _call(server, "POST", "/api/update/apply", {})
    assert status == 200 and d["ok"] is False and "up to date" in d["error"]


def test_a_refusal_reaches_the_operator_as_a_sentence(server, monkeypatch):
    """Not a 500 and not a traceback: the reasons this refuses are all things
    an operator can act on."""
    from corparius import selfupdate, update_check

    monkeypatch.setattr(
        update_check,
        "check",
        lambda *a, **k: {"enabled": True, "update_available": True, "latest": "9.9.9"},
    )

    def refuse(tag):
        raise selfupdate.UpdateError("checksum mismatch. Nothing was installed.")

    monkeypatch.setattr(selfupdate, "apply", refuse)
    status, d = _call(server, "POST", "/api/update/apply", {})
    assert status == 200 and d["ok"] is False and "Nothing was installed" in d["error"]


def test_the_tag_applied_is_the_one_the_check_reported(server, monkeypatch):
    from corparius import selfupdate, update_check

    seen = {}
    monkeypatch.setattr(
        update_check,
        "check",
        lambda *a, **k: {"enabled": True, "update_available": True, "latest": "0.2.0"},
    )
    monkeypatch.setattr(
        selfupdate, "apply", lambda tag: seen.setdefault("tag", tag) or {"ok": True, "backup": ""}
    )
    _call(server, "POST", "/api/update/apply", {})
    assert seen["tag"] == "v0.2.0"


# --- the CEO chat answered with the word "reply" ---------------------------
def test_the_chat_prompt_cannot_be_read_as_translate_this_word():
    """It said "Write 'reply' in French", and a model answered "Réponse" —
    reproduced live against llama-3.3-70b, three questions in a row, each
    answered with the label instead of an answer."""
    import inspect

    from corparius.app import chat as mod

    # Comment lines stripped: the comment there quotes the old wording on
    # purpose, and banning the explanation along with the mistake would be a
    # test that punishes writing down why.
    source = "\n".join(
        line
        for line in inspect.getsource(mod.once).splitlines()
        if not line.strip().startswith("#")
    )
    assert "Write 'reply' in" not in source
    assert "holds your answer to the operator" in source


def test_a_model_that_says_nothing_is_reported_as_such(server, monkeypatch):
    """`or message` echoed the operator's own question back, which reads like an
    answer and is not one."""
    from corparius import structured
    from corparius.app import chat as mod

    monkeypatch.setattr(
        structured,
        "ask",
        lambda *a, **k: structured.Result(
            {"reply": "", "intent": "answer"}, ok=False, attempts=2, source="groq:llama", raw=""
        ),
    )
    monkeypatch.setattr(mod, "HybridRouter", lambda s: object())
    status, d = _call(server, "POST", "/api/chat", {"company": "t", "message": "le site ?"})
    assert status == 200
    assert d["unanswered"] is True
    assert "le site ?" not in d["reply"], "the operator's own question came back"
    assert "did not answer" in d["reply"] or "n'a pas répondu" in d["reply"]


def test_a_real_answer_is_not_flagged_as_unanswered(server, monkeypatch):
    from corparius import structured
    from corparius.app import chat as mod

    monkeypatch.setattr(
        structured,
        "ask",
        lambda *a, **k: structured.Result(
            {"reply": "Oui, presque prêt.", "intent": "answer"},
            ok=True,
            attempts=1,
            source="groq:llama",
            raw="",
        ),
    )
    monkeypatch.setattr(mod, "HybridRouter", lambda s: object())
    _status, d = _call(server, "POST", "/api/chat", {"company": "t", "message": "le site ?"})
    assert d["unanswered"] is False and d["reply"] == "Oui, presque prêt."


def test_the_consoles_javascript_parses():
    """Nothing else checks it, and it is a single 180 000-character inline
    script edited by hand. One stray brace makes the whole console a blank page
    with an error only the browser sees — no test, no lint and no type checker
    in this repo would say a word.

    Skipped where node is absent, like the generated Netlify function's check.
    """
    import re
    import shutil
    import subprocess
    import tempfile
    from pathlib import Path

    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    html = Path("corparius/webui.html").read_text(encoding="utf-8")
    blocks = re.findall(r"<script[^>]*>(.*?)</script>", html, re.S)
    assert blocks, "the console has no script block; this test is watching nothing"
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "console.mjs"
        path.write_text("\n".join(blocks), encoding="utf-8")
        proc = subprocess.run([node, "--check", str(path)], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr


def test_the_done_column_is_bounded_and_says_the_true_count(server):
    """Completed tasks only ever accumulate. One console showed thirty-six of
    them, oldest first, pushing everything below the board off the page — and
    the renderer cut at thirty without saying so, so the header disagreed with
    the column under it."""
    from corparius.webui import DONE_KEPT

    store = server.RequestHandlerClass.state.store()
    for i in range(DONE_KEPT + 12):
        store.add_task("example", f"Task {i}", "design", status="done")

    _, data = _call(server, "GET", "/api/overview?company=example")
    sent = data["tasks"]["done"]
    assert len(sent) == DONE_KEPT, "the payload is bounded"
    assert data["done_total"] == DONE_KEPT + 12, "and the count is the real one"
    assert sent[0]["title"] == f"Task {DONE_KEPT + 11}", "newest first, not the first ever done"
