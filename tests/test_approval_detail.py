"""Approving something you cannot read is not approval, it is assent.

An approval carried `parameters`, and `parameters` carried the draft cut to 80
characters — not out of carelessness but because the approval id is an md5 of
those parameters, and a longer draft would have made the same request look new
on every tick. The console then rendered that as a JSON dump.

So the operator's whole view of "send this cold email" was eighty characters of
it, in braces. The full text lives in `detail` now, which nothing hashes.
"""

import json

from corparius.hitl import ApprovalGate
from corparius.permissions import EXTERNAL, MONEY, PermissionEngine, explain
from corparius.store import Store
from corparius.tools import TOOLS

EMAIL = "Bonjour,\n\n" + ("Votre équipe passe des heures à lire des CV. " * 8)


def _raise_one(store, tool_name="send_outreach", draft=EMAIL):
    gate = ApprovalGate(store, PermissionEngine([tool_name]))
    ctx = type("Ctx", (), {"store": store, "company": {"slug": "t"}})()
    gate.execute("t", "outreach", TOOLS[tool_name], ctx, draft, {"draft": draft[:80]})
    return next(a for a in store.list_approvals("t", "pending") if a["tool"] == tool_name)


def test_the_whole_draft_is_kept_not_eighty_characters(tmp_path):
    store = Store(str(tmp_path))
    approval = _raise_one(store)
    detail = json.loads(approval["detail"])
    assert len(detail["draft"]) == len(EMAIL)
    assert detail["draft"] == EMAIL
    # And the parameters are still the short form, because the id hashes them.
    assert len(json.loads(approval["parameters"])["draft"]) == 80
    store.close()


def test_the_id_still_does_not_move_when_the_draft_is_long(tmp_path):
    """The reason the draft was cut in the first place. If keeping it whole made
    every tick file a fresh approval, this would be a worse bug than the one it
    fixes."""
    store = Store(str(tmp_path))
    first = _raise_one(store)["id"]
    store.close()
    store = Store(str(tmp_path))
    second = _raise_one(store)["id"]
    assert first == second
    store.close()


def test_the_detail_says_what_the_tool_does_and_why_it_stopped(tmp_path):
    store = Store(str(tmp_path))
    detail = json.loads(_raise_one(store)["detail"])
    assert detail["does"] == TOOLS["send_outreach"].description
    assert "gated by name" in detail["why"]
    store.close()


def test_a_tool_with_no_draft_carries_no_draft(tmp_path):
    """`send_financial_transaction` takes no draft. An empty string is the
    honest answer, not a placeholder that looks like content."""
    store = Store(str(tmp_path))
    detail = json.loads(_raise_one(store, "send_financial_transaction", "")["detail"])
    assert detail["draft"] == ""
    assert detail["does"]
    store.close()


def test_a_risk_class_is_explained_in_words_an_operator_can_act_on():
    """The badge says "external". That is a category, not a consequence."""
    assert "cannot be taken back" in explain(EXTERNAL)
    assert "money" in explain(MONEY).lower()
    assert explain("nonsense-class") == explain("read"), "an unknown class is treated as harmless"


def test_the_console_resolves_everything_the_panel_needs(tmp_path, monkeypatch):
    """Resolved server-side rather than in the page: what a tool does and what a
    risk means are facts about this build, not about the browser."""
    monkeypatch.setenv("CORP_DATA_PATH", str(tmp_path))
    monkeypatch.setenv("CORP_HOME", str(tmp_path))
    (tmp_path / "companies" / "t").mkdir(parents=True)
    (tmp_path / "companies" / "t" / "company.yaml").write_text(
        "slug: t\nname: T\nhitl_tools: [send_outreach]\n", encoding="utf-8"
    )
    from corparius import webui

    store = Store(str(tmp_path))
    _raise_one(store)
    store.close()

    state = webui.UiState(webui._fresh_settings(), tmp_path / ".env")
    overview = webui._overview(state, "t")
    state.close()
    approval = next(a for a in overview["approvals"] if a["tool"] == "send_outreach")
    detail = approval["detail"]
    assert detail["draft"] == EMAIL
    assert detail["does"] and detail["risk_means"]
    assert "runs once" in detail["on_approve"]
    assert "Nothing runs" in detail["on_reject"]


def test_an_approval_written_before_this_column_existed_still_renders(tmp_path, monkeypatch):
    """A store migrated from v7 has approvals with no detail at all. The panel
    has to degrade to what the tool registry knows, not blow up."""
    monkeypatch.setenv("CORP_DATA_PATH", str(tmp_path))
    monkeypatch.setenv("CORP_HOME", str(tmp_path))
    (tmp_path / "companies" / "t").mkdir(parents=True)
    (tmp_path / "companies" / "t" / "company.yaml").write_text(
        "slug: t\nname: T\n", encoding="utf-8"
    )
    from corparius import webui
    from corparius.kernel.records import ApprovalRequest

    store = Store(str(tmp_path))
    store.add_approval(
        ApprovalRequest(
            id="old", company="t", agent="outreach", tool="send_outreach", parameters={}
        )
    )
    store.db.execute("UPDATE approvals SET detail=NULL WHERE id='old'")
    store.db.commit()
    store.close()

    state = webui.UiState(webui._fresh_settings(), tmp_path / ".env")
    approval = next(a for a in webui._overview(state, "t")["approvals"] if a["id"] == "old")
    state.close()
    assert approval["detail"]["draft"] == ""
    assert approval["detail"]["does"] == TOOLS["send_outreach"].description
