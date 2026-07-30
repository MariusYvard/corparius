"""What the operator has to do themselves, made findable.

Two complaints from a real session, both about the same thing — corparius knew
what was wrong and left the operator to work out what to do about it.

"La configuration de l'email est encore trop complexe et les tâches à faire
soi-même ne sont pas guidées." The preset filled four hostnames, which is the
easy half; the hard half happens on somebody else's website behind two-factor
authentication, and the console said nothing about it.

And `scan_replies` / `triage_inbox` returned "No mailbox connected" on every
tick of every run. True, correct, and useless: a line in the action log,
repeated forever, pointing at nothing anyone could click.
"""

import types

import pytest

from corparius import inbox as inbox_mod
from corparius import mailbox, settings_spec, webui
from corparius.store import Store
from corparius.tools import TOOLS

# --------------------------------------------------------------------------
# Guided mail
# --------------------------------------------------------------------------


def test_every_mail_preset_has_steps():
    """A provider in the dropdown with no steps is the old experience, kept for
    whoever happens to pick that one."""
    missing = [
        p["id"] for p in settings_spec.MAIL_PRESETS if p["id"] not in settings_spec.MAIL_STEPS
    ]
    assert not missing, missing


def test_the_steps_are_written_in_both_languages():
    for provider, steps in settings_spec.MAIL_STEPS.items():
        for i, step in enumerate(steps):
            assert step.get("en", "").strip(), f"{provider}[{i}]"
            assert step.get("fr", "").strip(), f"{provider}[{i}]"


def test_a_step_that_names_a_setting_names_a_real_one():
    """`needs` decides whether a step shows as done. A typo there is a step that
    can never turn green, which is worse than no state at all."""
    for provider, steps in settings_spec.MAIL_STEPS.items():
        for step in steps:
            for key in step.get("needs") or []:
                assert key in settings_spec.BY_KEY, f"{provider}: {key}"


def test_every_link_is_an_https_url():
    for provider, steps in settings_spec.MAIL_STEPS.items():
        for step in steps:
            url = step.get("url", "")
            if url:
                assert url.startswith("https://"), f"{provider}: {url}"


def test_the_hard_step_carries_the_link_that_makes_it_doable():
    """Gmail is the case that motivated this: an app password lives behind
    2-Step Verification, on a page nobody finds by guessing."""
    steps = settings_spec.MAIL_STEPS["gmail"]
    urls = [s.get("url", "") for s in steps]
    assert any("two-step-verification" in u for u in urls)
    assert any("apppasswords" in u for u in urls)


def test_a_step_reports_done_from_the_settings_not_from_a_checkbox(monkeypatch):
    from corparius import cfg

    values = {}
    monkeypatch.setattr(cfg, "get", lambda key, default="": values.get(key, default))

    steps = webui._mail_steps()["gmail"]
    checkable = [s for s in steps if s["checkable"]]
    assert checkable and not any(s["done"] for s in checkable)

    values["CORP_SMTP_USER"] = "a@b.c"
    values["CORP_SMTP_PASSWORD"] = "x" * 16
    assert all(s["done"] for s in webui._mail_steps()["gmail"] if s["checkable"])


def test_a_step_nobody_can_verify_says_so_rather_than_staying_unticked(monkeypatch):
    """Installing Proton Bridge is real work corparius cannot observe. A
    checkbox that can never turn green reads as a failure."""
    from corparius import cfg

    monkeypatch.setattr(cfg, "get", lambda key, default="": "")
    steps = webui._mail_steps()["proton"]
    assert any(not s["checkable"] for s in steps)
    assert all(not s["done"] for s in steps if not s["checkable"])


def test_the_console_is_given_the_steps():
    payload = webui._settings_payload()
    assert payload["mail_steps"]
    assert set(payload["mail_steps"]) == set(settings_spec.MAIL_STEPS)


# --------------------------------------------------------------------------
# The complaint that repeated forever
# --------------------------------------------------------------------------


def _ctx(store):
    return types.SimpleNamespace(
        store=store, company={"slug": "t", "name": "T"}, role="support", leads=[]
    )


def test_no_mailbox_is_filed_once_not_every_tick(tmp_path, monkeypatch):
    monkeypatch.setattr(mailbox, "configured", lambda: False)
    store = Store(str(tmp_path))
    ctx = _ctx(store)

    for _ in range(8):
        TOOLS["triage_inbox"].run(ctx)
        TOOLS["scan_replies"].run(ctx)
        TOOLS["draft_support_reply"].skip_reason(ctx)

    notices = [m for m in store.list_inbox("t", "pending") if "mailbox" in m["title"].lower()]
    assert len(notices) == 1, f"{len(notices)} notices after eight ticks"
    store.close()


def test_the_notice_names_where_it_is_fixed(tmp_path, monkeypatch):
    monkeypatch.setattr(mailbox, "configured", lambda: False)
    store = Store(str(tmp_path))
    TOOLS["triage_inbox"].run(_ctx(store))
    notice = next(m for m in store.list_inbox("t", "pending") if "mailbox" in m["title"].lower())
    assert notice["fix"] == "mail"
    assert notice["fix"] in inbox_mod.FIXES
    store.close()


def test_still_no_fabricated_numbers_in_the_output(tmp_path, monkeypatch):
    """The older rule this must not undo: without a mailbox, no counts."""
    monkeypatch.setattr(mailbox, "configured", lambda: False)
    store = Store(str(tmp_path))
    out = TOOLS["triage_inbox"].run(_ctx(store))
    assert "No mailbox connected" in out.output
    assert not any(ch.isdigit() for ch in out.output)
    store.close()


def test_a_tool_with_no_store_still_answers(tmp_path, monkeypatch):
    """Several callers build a context by hand and pass no store. Filing the
    notice must not become a new way for a tool to crash."""
    monkeypatch.setattr(mailbox, "configured", lambda: False)
    ctx = types.SimpleNamespace(company={"slug": "t", "name": "T"})
    assert "No mailbox connected" in TOOLS["triage_inbox"].run(ctx).output


def test_every_fix_points_at_a_tab_the_console_actually_has():
    """A notice pointing at a tab nobody built renders a button that does
    nothing, which is worse than the log line it replaced."""
    with open("corparius/webui.html", encoding="utf-8") as fh:
        page = fh.read()
    for name, tab in inbox_mod.FIXES.items():
        assert f'id="t-{tab}"' in page, f"{name} -> #t-{tab} does not exist"


def test_every_fix_has_a_button_label_in_both_languages():
    with open("corparius/webui.html", encoding="utf-8") as fh:
        page = fh.read()
    for name in inbox_mod.FIXES:
        assert page.count(f'"ib.fix.{name}"') >= 2, f"{name} is missing an EN or FR label"


def test_an_unknown_fix_is_refused_rather_than_rendering_a_dead_button(tmp_path, caplog):
    store = Store(str(tmp_path))
    inbox_mod.notify(store, "t", "system", "Something", "body", fix="nowhere")
    item = next(m for m in store.list_inbox("t", "pending") if m["title"] == "Something")
    assert item["fix"] == ""
    store.close()


def test_a_notice_written_before_this_column_existed_still_renders(tmp_path):
    """A store migrated from v8 has inbox rows with fix NULL. The page reads it
    to decide whether to draw a button, and null is not ""."""
    store = Store(str(tmp_path))
    store.add_inbox("t", "system", "notification", "Old one", "body")
    store.db.execute("UPDATE inbox SET fix=NULL")
    store.db.commit()
    item = next(m for m in store.list_inbox("t", "pending") if m["title"] == "Old one")
    assert item["fix"] == ""
    store.close()


@pytest.mark.parametrize("tool", ["triage_inbox", "scan_replies"])
def test_a_connected_mailbox_files_nothing(tmp_path, monkeypatch, tool):
    monkeypatch.setattr(mailbox, "configured", lambda: True)
    monkeypatch.setattr(mailbox, "fetch", lambda limit=40: [])
    store = Store(str(tmp_path))
    TOOLS[tool].run(_ctx(store))
    assert not [m for m in store.list_inbox("t", "pending") if "mailbox" in m["title"].lower()]
    store.close()


# --------------------------------------------------------------------------
# Scoping a skill that rides on every prompt
# --------------------------------------------------------------------------

UNSCOPED = """---
name: promesse
description: What this company may never claim, in one long sentence that a YAML dumper would fold across two lines if it were allowed to.
---

Never claim a clinical outcome.

Second paragraph, with  odd   spacing kept on purpose.
"""


def _skill(tmp_path, text=UNSCOPED):
    from pathlib import Path

    folder = Path(tmp_path) / "promesse"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "SKILL.md"
    path.write_text(text, encoding="utf-8")
    return path


def test_scoping_a_skill_leaves_the_prose_byte_for_byte(tmp_path):
    """The operator's words are in this file. Rewriting a header must not
    reformat, re-wrap or re-indent a single line of them."""
    from corparius import skills

    path = _skill(tmp_path)
    before = skills.parse(path)
    assert before.unscoped

    assert skills.scope_to(path, ["draft_support_reply", "send_outreach"]) == ""
    after = skills.parse(path)

    assert after is not None, "the rewritten file no longer parses"
    assert after.instructions == before.instructions
    assert after.description == before.description
    assert after.allowed_tools == ["draft_support_reply", "send_outreach"]
    assert not after.unscoped


def test_the_closing_fence_keeps_its_newline(tmp_path):
    """The bug this found. `_split` drops the newline that ended the closing
    fence; writing `---{body}` merged it into the first line of the prose, the
    file lost its frontmatter entirely, and `parse` read the whole thing as body
    — an unscoped skill twice the size, which is the opposite of the point."""
    from corparius import skills

    path = _skill(tmp_path)
    skills.scope_to(path, ["send_outreach"])
    raw = path.read_text(encoding="utf-8")
    assert "\n---\n" in raw
    assert "---Never claim" not in raw
    assert skills.parse(path).allowed_tools == ["send_outreach"]


def test_a_long_description_is_not_folded_across_lines(tmp_path):
    """Valid YAML either way, and still an unasked-for edit to a sentence
    somebody wrote."""
    from corparius import skills

    path = _skill(tmp_path)
    skills.scope_to(path, ["send_outreach"])
    head = path.read_text(encoding="utf-8").split("---")[1]
    description = [ln for ln in head.splitlines() if ln.startswith("description:")]
    assert len(description) == 1
    assert description[0].rstrip().endswith("allowed to.")


def test_scoping_is_idempotent(tmp_path):
    from corparius import skills

    path = _skill(tmp_path)
    skills.scope_to(path, ["send_outreach"])
    once = path.read_text(encoding="utf-8")
    skills.scope_to(path, ["send_outreach"])
    assert path.read_text(encoding="utf-8") == once


def test_a_tool_that_does_not_exist_is_refused(tmp_path):
    """A skill scoped to a name nobody has never applies, silently — a worse
    outcome than the tax it was meant to fix."""
    from corparius import skills

    path = _skill(tmp_path)
    before = path.read_text(encoding="utf-8")
    error = skills.scope_to(path, ["send_outreach", "not_a_tool"])
    assert "not_a_tool" in error
    assert path.read_text(encoding="utf-8") == before, "the file was touched anyway"


def test_an_empty_tool_list_is_refused(tmp_path):
    from corparius import skills

    path = _skill(tmp_path)
    assert "at least one tool" in skills.scope_to(path, [])
    assert skills.parse(path).unscoped


def test_a_file_with_no_frontmatter_is_refused_rather_than_mangled(tmp_path):
    """`_split` returns everything as body when there is no frontmatter. Writing
    a header onto it would work, but the pre-write parse check is what stops any
    rewrite that would not read back."""
    from corparius import skills

    path = _skill(tmp_path, "Just a note somebody typed, no frontmatter at all.\n")
    error = skills.scope_to(path, ["send_outreach"])
    assert error == "" or "not parse" in error
    assert skills.parse(path) is not None


def test_no_temporary_file_is_left_behind(tmp_path):
    from corparius import skills

    path = _skill(tmp_path)
    skills.scope_to(path, ["send_outreach"])
    assert sorted(p.name for p in path.parent.iterdir()) == ["SKILL.md"]
