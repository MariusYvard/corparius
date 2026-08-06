"""The company writes down the procedure that avoids a repeated failure.

The producing half of the skill system, which did not exist: `write_skill`, `create_skill` and
`save_skill` had zero occurrences in the package while all of `skills.py` waited for an author,
and only the operator could be one. See docs/reverse-engineering/hermes-agent.md.

Three guards, and this file is mostly about the first two, because they are the ones code can
hold:

1. **Scope is set here, not by the model.** `allowed-tools` is the tool that actually failed,
   so an agent-written skill cannot be unscoped — and an unscoped skill rides on every prompt
   of every turn, which is the cost `always_on_chars()` exists to measure and the one this
   feature could plausibly have made worse.
2. **The name becomes a directory**, so it is slugified and has to survive it.
3. The negative guardrail is in the prompt, because no code can tell "check the mailbox is
   connected first" from "the mailbox was down".
"""

import types

import pytest

from corparius.kernel import paths
from corparius.skills import SkillLoader, parse
from corparius.store import Store
from corparius.tools import effects
from corparius.tools.registry import TOOLS


@pytest.fixture()
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("CORP_HOME", str(tmp_path))
    monkeypatch.setenv("CORP_DATA_PATH", str(tmp_path / "data"))
    return tmp_path


@pytest.fixture()
def store(home):
    s = Store(str(home / "data"))
    yield s
    s.close()


def _ctx(store, *, instructions="Check the mailbox is connected first.", name="", failures=2):
    for _ in range(failures):
        store.record_action("acme", "support", "draft_support_reply", {}, "no mailbox", False)
    return types.SimpleNamespace(
        company={"slug": "acme", "name": "Acme"},
        store=store,
        structured=types.SimpleNamespace(
            data={"name": name, "description": "", "instructions": instructions},
            ok=True,
            fell_back=False,
            errors=[],
            source="mock",
            attempts=1,
        ),
    )


def _written(slug="acme"):
    return sorted(p.parent.name for p in paths.company_skills_dir(slug).glob("*/SKILL.md"))


# --- it only fires on a pattern ----------------------------------------------


def test_one_failure_is_not_a_pattern(store):
    """Once is noise — a rate limit, a network blip, exactly what the guardrail says never to
    record. The tool skips itself rather than writing a skill about weather."""
    ctx = _ctx(store, failures=1)
    assert "no pattern to write down" in TOOLS["write_skill"].skip_reason(ctx)
    assert TOOLS["write_skill"].draft_prompt(ctx) == "", "and nothing is asked of a model"
    assert _written() == []


def test_twice_is(store):
    ctx = _ctx(store)
    assert TOOLS["write_skill"].skip_reason(ctx) == ""
    assert "draft_support_reply" in TOOLS["write_skill"].draft_prompt(ctx)


def test_a_clean_company_writes_nothing(store):
    ctx = _ctx(store, failures=0)
    reason = TOOLS["write_skill"].skip_reason(ctx)
    assert "no pattern to write down" in reason
    assert TOOLS["write_skill"].draft_prompt(ctx) == ""


def test_its_own_failures_never_become_a_skill(store):
    """A skill about how to fail at writing a skill is a joke the library does not need — and
    it would be self-sustaining, which is worse."""
    for _ in range(4):
        store.record_action("acme", "ceo", "write_skill", {}, "could not write", False)
    ctx = _ctx(store, failures=0)
    assert TOOLS["write_skill"].skip_reason(ctx), "it must not learn from itself"


# --- the guards code can hold ------------------------------------------------


def test_the_skill_is_scoped_to_the_tool_that_failed(store):
    """The load-bearing guard. The model never gets to choose the scope, so an agent-written
    skill cannot join the block that rides on every prompt of every turn."""
    out = TOOLS["write_skill"].run(_ctx(store))
    assert out.ok and "draft_support_reply" in out.output
    skill = parse(
        paths.company_skills_dir("acme") / "avoid-draft-support-reply-failure" / "SKILL.md"
    )
    assert skill is not None
    assert skill.allowed_tools == ["draft_support_reply"]
    assert not skill.unscoped, "an agent-written skill must never be unscoped"


def test_no_agent_written_skill_can_be_always_on(store):
    """The same property, stated as the console would ask it: whatever the company writes for
    itself costs the turns of one tool, never every turn of every agent."""
    TOOLS["write_skill"].run(_ctx(store))
    loader = SkillLoader.for_company("acme")
    assert loader.always_on_chars() == 0
    assert loader.context_for("draft_support_reply"), "and it does reach the tool it is for"
    assert loader.context_for("reconcile_stripe") == "", "and no other"


@pytest.mark.parametrize(
    "hostile",
    [
        "../../../../etc/passwd",
        "..\\..\\windows",
        "/absolute/path",
        "name with spaces and .. dots",
        "Méthode et Architecture",
    ],
)
def test_a_hostile_name_cannot_escape_the_company_folder(store, hostile):
    """The name becomes a directory. `_load_company` guards a slug against the glob that
    produced it and `kernel/dotenv.merge` refuses a newline in a value; this is the same
    class, and the answer is the same — slugify, and refuse what does not survive it."""
    out = TOOLS["write_skill"].run(_ctx(store, name=hostile))
    assert out.ok
    written = _written()
    assert len(written) == 1
    assert ".." not in written[0] and "/" not in written[0] and "\\" not in written[0]
    # And nothing landed outside the company's own skills folder.
    assert (paths.company_skills_dir("acme") / written[0] / "SKILL.md").is_file()


def test_a_name_that_slugifies_to_nothing_is_refused_not_repaired(store):
    out = TOOLS["write_skill"].run(_ctx(store, name="!!! ??? ***"))
    assert "leaves nothing usable" in out.output
    assert _written() == [], "no folder should have been created"


def test_an_operator_written_skill_is_never_overwritten(store):
    """The operator keeps the last word by construction, exactly as EXTRA_DIRS already
    promises for plugin skills. The author marker is what tells them apart."""
    folder = paths.company_skills_dir("acme") / "mine"
    folder.mkdir(parents=True)
    hand_written = "---\nname: mine\ndescription: I wrote this.\n---\nDo it my way.\n"
    (folder / "SKILL.md").write_text(hand_written, encoding="utf-8")
    out = TOOLS["write_skill"].run(_ctx(store, name="mine"))
    assert "refused to overwrite" in out.output
    assert (folder / "SKILL.md").read_text(encoding="utf-8") == hand_written


def test_its_own_earlier_skill_is_replaced_rather_than_duplicated(store):
    """The other direction. Two skills about the same failure are the library rot Hermes'
    curator exists to undo, and here it is cheaper not to create it."""
    TOOLS["write_skill"].run(_ctx(store, name="mailbox-first", instructions="First version."))
    TOOLS["write_skill"].run(_ctx(store, name="mailbox-first", instructions="Second version."))
    assert _written() == ["mailbox-first"]
    body = (paths.company_skills_dir("acme") / "mailbox-first" / "SKILL.md").read_text(
        encoding="utf-8"
    )
    assert "Second version." in body and "First version." not in body


def test_the_library_is_capped(store):
    """A cap rather than a rate: what matters is the size of the library, not how fast it
    grew. Past it the tool says so instead of adding the next one."""
    for i in range(effects.SKILL_WRITE_MAX):
        folder = paths.company_skills_dir("acme") / f"written-{i}"
        folder.mkdir(parents=True)
        (folder / "SKILL.md").write_text(
            f"---\nname: written-{i}\nauthor: {effects.AGENT_AUTHOR}\nallowed-tools: x\n---\nb\n",
            encoding="utf-8",
        )
    reason = TOOLS["write_skill"].skip_reason(_ctx(store))
    assert "already written" in reason and "consolidate" in reason


def test_the_operators_own_skills_do_not_count_against_the_cap(store):
    """Identified by the marker, not by location: an operator may keep their skills in the
    same folder, and filling it should not silence the company's own learning."""
    for i in range(effects.SKILL_WRITE_MAX + 5):
        folder = paths.company_skills_dir("acme") / f"theirs-{i}"
        folder.mkdir(parents=True)
        (folder / "SKILL.md").write_text(
            f"---\nname: theirs-{i}\nallowed-tools: x\n---\nbody\n", encoding="utf-8"
        )
    assert TOOLS["write_skill"].skip_reason(_ctx(store)) == ""


# --- the prompt --------------------------------------------------------------


def test_the_prompt_forbids_recording_a_transient_failure(store):
    """The most transferable line in hermes-agent, and this project has been bitten by the
    shape twice: `promesse-clinique` riding 36 tool calls, and TRIES_BEFORE_STAND_DOWN. A
    skill saying "the SMTP server is down" would be a permanent belief."""
    prompt = TOOLS["write_skill"].draft_prompt(_ctx(store))
    assert "Do NOT write down" in prompt
    assert "rate limit" in prompt and "next month" in prompt


def test_the_prompt_quotes_what_actually_happened(store):
    """The correction to `remember`, whose prompt asks a model what the company learned today
    without showing it the day. Here the failures are in the prompt."""
    prompt = TOOLS["write_skill"].draft_prompt(_ctx(store))
    assert "no mailbox" in prompt, "the real output has to reach the prompt"
    assert "draft_support_reply" in prompt


def test_an_empty_draft_writes_no_skill(store):
    ctx = _ctx(store, instructions="")
    out = TOOLS["write_skill"].run(ctx)
    assert _written() == []
    assert out.output.strip()


def test_no_provider_answering_is_not_an_empty_skill(store):
    """Same distinction `_empty_draft` was written for: "it had nothing to add" and "every
    provider refused" are different facts, and reporting them as one sent an operator hunting
    a site generator after spending 365 026 tokens."""
    ctx = _ctx(store, instructions="")
    ctx.structured = types.SimpleNamespace(
        data={"instructions": ""}, ok=False, fell_back=True, errors=["429"], source="", attempts=3
    )
    out = TOOLS["write_skill"].run(ctx)
    assert "routing problem" in out.output
    assert _written() == []


def test_a_disk_failure_does_not_fail_the_turn(store, monkeypatch):
    monkeypatch.setattr(
        effects.Path, "write_text", lambda *a, **k: (_ for _ in ()).throw(OSError("full"))
    )
    out = TOOLS["write_skill"].run(_ctx(store))
    assert out.ok and "could not write the skill" in out.output
