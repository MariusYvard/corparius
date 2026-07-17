"""The company editor and the actions that used to need a shell: deploy, backup,
task editing, a headline. Everything here exists so the operator never has to
open a file.
"""
import threading

import pytest
import yaml

from app import cfg, company as company_mod, webui
from app.config import Settings
from app.store import Store

from .test_webui import _call


@pytest.fixture()
def server(tmp_path, monkeypatch):
    monkeypatch.setenv("CORP_DATA_PATH", str(tmp_path / "data"))
    monkeypatch.setenv("CORP_LLM_MOCK", "true")
    monkeypatch.delenv("CORP_UI_TOKEN", raising=False)
    root = tmp_path / "root"
    (root / "companies" / "acme").mkdir(parents=True)
    (root / "companies" / "acme" / "company.yaml").write_text(
        "slug: acme\nname: Acme\noffer:\n  product: Widgets\n", encoding="utf-8")
    monkeypatch.setattr(company_mod, "ROOT", root)
    cfg.set_dotenv_path(tmp_path / ".env")
    cfg.invalidate()
    srv = webui.build_server(Settings(), host="127.0.0.1", port=0, env_file=tmp_path / ".env")
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv
    srv.shutdown()


def test_reads_a_company_with_every_field_filled_in(server):
    status, d = _call(server, "GET", "/api/company?company=acme")
    assert status == 200 and d["ok"]
    c = d["company"]
    # The file only had four keys; the shared validator supplies the rest, so the
    # editor never opens a company with holes in it.
    assert set(c) == {"slug", "name", "one_liner", "offer", "icp", "agents",
                      "budgets", "hitl_tools"}
    assert c["offer"]["billing"] == "stripe" and c["icp"]["channels"] == ["linkedin"]
    assert d["roles"] and d["channels"] and d["tools"]


def test_edits_every_field_the_wizard_used_to_hardcode(server):
    _, before = _call(server, "GET", "/api/company?company=acme")
    cfg_in = before["company"]
    cfg_in["offer"] = {"product": "Widgets", "price_eur": 29, "billing": "manual",
                       "payment_link": "https://pay.example/x"}
    cfg_in["icp"] = {"segment": "Toolmakers", "channels": ["x", "reddit"],
                     "pains": ["slow", "costly"]}
    cfg_in["budgets"] = {"session_tokens": 40000, "tokens_per_minute": 3000,
                         "daily_ad_spend_eur": 12}
    cfg_in["agents"] = {**cfg_in["agents"], "ads": True}
    cfg_in["hitl_tools"] = ["send_financial_transaction"]
    status, d = _call(server, "POST", "/api/company", {"company": "acme", "config": cfg_in})
    assert status == 200 and d["ok"], d.get("error")

    on_disk = yaml.safe_load((company_mod.path_for("acme")).read_text(encoding="utf-8"))
    assert on_disk["offer"]["price_eur"] == 29
    assert on_disk["offer"]["payment_link"] == "https://pay.example/x"
    assert on_disk["icp"]["channels"] == ["x", "reddit"]
    assert on_disk["budgets"]["daily_ad_spend_eur"] == 12
    assert on_disk["hitl_tools"] == ["send_financial_transaction"]


def test_bad_input_is_refused_with_a_reason_not_a_traceback(server):
    _, before = _call(server, "GET", "/api/company?company=acme")
    bad = {**before["company"], "name": ""}
    status, d = _call(server, "POST", "/api/company", {"company": "acme", "config": bad})
    assert status == 400 and d["ok"] is False and "name is required" in d["error"]
    status, d = _call(server, "POST", "/api/company",
                      {"company": "nope", "config": before["company"]})
    assert d["ok"] is False


def test_unknown_values_are_repaired_and_reported(server):
    _, before = _call(server, "GET", "/api/company?company=acme")
    cfg_in = {**before["company"]}
    cfg_in["icp"] = {**cfg_in["icp"], "channels": ["linkedin", "carrier-pigeon"]}
    cfg_in["agents"] = {**cfg_in["agents"], "wizard": True}
    status, d = _call(server, "POST", "/api/company", {"company": "acme", "config": cfg_in})
    assert status == 200 and d["ok"]
    warned = " ".join(d["warnings"])
    assert "carrier-pigeon" in warned and "wizard" in warned
    assert d["company"]["icp"]["channels"] == ["linkedin"]
    assert "wizard" not in d["company"]["agents"]


def test_delete_needs_the_slug_typed_and_only_moves_the_config(server):
    status, d = _call(server, "POST", "/api/company/delete", {"company": "acme", "confirm": "no"})
    assert status == 400 and d["ok"] is False
    assert company_mod.path_for("acme").is_file()

    status, d = _call(server, "POST", "/api/company/delete",
                      {"company": "acme", "confirm": "acme"})
    assert status == 200 and d["ok"] and "acme" not in d["companies"]
    # Moved aside, never destroyed: a mistyped slug must be recoverable.
    trashed = list((company_mod.ROOT / "companies" / ".trash").glob("acme-*"))
    assert trashed and (trashed[0] / "company.yaml").is_file()


def test_a_broken_company_file_opens_for_repair_instead_of_crashing(server):
    (company_mod.ROOT / "companies" / "blank").mkdir()
    (company_mod.ROOT / "companies" / "blank" / "company.yaml").write_text("", encoding="utf-8")
    status, d = _call(server, "GET", "/api/company?company=blank")
    # This used to raise AttributeError from inside setdefault() on None. A 404
    # would be no better: it would strand the operator with a listed company and
    # no way to fix it. So: open it, and name what is missing.
    assert status == 200 and d["ok"]
    assert "name is required" in d["problems"]
    assert "offer.product is required" in d["problems"]
    # And it is repairable from the same screen.
    fixed = {**d["company"], "name": "Blank Co", "offer": {"product": "Something"}}
    status, d = _call(server, "POST", "/api/company", {"company": "blank", "config": fixed})
    assert status == 200 and d["ok"] and not d["problems"]

    # A file that is not a mapping at all is refused rather than half-read.
    (company_mod.ROOT / "companies" / "wrong").mkdir()
    (company_mod.ROOT / "companies" / "wrong" / "company.yaml").write_text(
        "- just\n- a list\n", encoding="utf-8")
    status, d = _call(server, "GET", "/api/company?company=wrong")
    assert status == 404 and d["ok"] is False


def test_task_can_be_retitled_and_reprioritised_not_only_decided(server):
    store = Store(str(server.RequestHandlerClass.state.settings.data_path))
    store.add_task("acme", "vague idea", "social", status="proposed")
    tid = store.list_tasks("acme", "proposed")[0]["id"]

    status, d = _call(server, "POST", "/api/tasks",
                      {"id": tid, "title": "Publish the launch post", "priority": 3})
    assert status == 200 and d["ok"] and set(d["changed"]) == {"title", "priority"}
    task = store.list_tasks("acme")[0]
    assert task["title"] == "Publish the launch post" and task["priority"] == 3
    assert task["status"] == "proposed", "editing must not silently decide"

    status, d = _call(server, "POST", "/api/tasks", {"id": tid, "decision": "approved"})
    assert status == 200 and store.list_tasks("acme", "approved")

    for bad in ({"id": tid, "target": "nobody"}, {"id": tid, "tool": "no_such_tool"},
                {"id": tid, "title": "  "}, {"id": tid}):
        status, d = _call(server, "POST", "/api/tasks", bad)
        assert status == 400 and d["ok"] is False


def test_site_takes_a_headline_and_deploy_says_what_happened(server, monkeypatch):
    status, d = _call(server, "POST", "/api/site",
                      {"company": "acme", "headline": "Widgets that survive Monday"})
    assert status == 200 and d["ok"]
    from app import paths
    html = paths.site_index(server.RequestHandlerClass.state.settings.data_path, "acme").read_text(encoding="utf-8")
    assert "Widgets that survive Monday" in html   # CLI-only until now

    status, d = _call(server, "POST", "/api/deploy", {"company": "acme"})
    assert status == 200 and d["published"] is True and d["provider"] == "local"

    # With no provider reachable, the console must say nothing was published
    # rather than log a failure as a success.
    monkeypatch.setenv("CORP_DEPLOY_PROVIDERS", "netlify")
    for var in ("NETLIFY_AUTH_TOKEN",):
        monkeypatch.delenv(var, raising=False)
    status, d = _call(server, "POST", "/api/deploy", {"company": "acme"})
    assert status == 200 and d["published"] is False and not d["provider"]


def test_backup_writes_a_zip_and_says_it_holds_the_keys(server):
    status, d = _call(server, "POST", "/api/backup", {})
    assert status == 200 and d["ok"] and d["name"].endswith(".zip") and d["size"] > 0
    assert "clear" in d["warning"]["en"] and "clair" in d["warning"]["fr"]
