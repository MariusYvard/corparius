"""A role that has nothing to do yet, and the day's shape.

Two changes with one motive: a turn should be spent on work rather than on motion.

**The gate.** Cadence answers "has enough time passed" and a `pause` directive answers "the operator
said stop". Neither could answer "is there anything here to do", and the gap was visible in the
shipped example config for as long as it has existed:

    ads: false        # off until there is budget to spend

An operator maintaining by hand a fact the runtime could read. Ads on a company with no page and no
checkout adjusts bids on a campaign that does not exist; outreach with no public address sends a link
to nothing; support with no mailbox drafts a reply to nobody, which this project has already paid for
once. Each of those is a real model call and a real line in the log that looks like work.

**The offsets.** `tick % cadence == 0` put every role on hour 0 and on every multiple of 24 after it,
while the roster's own docstring promised the cadences were staggered "so the company does not spend
its whole budget in one burst". The README's cadence figure draws the contradiction as a column of
dots down the 00h line.
"""

import pathlib

import pytest

from corparius import readiness
from corparius.kernel.records import AgentRole
from corparius.orchestrator import due_roles, held_roles, paused_roles
from corparius.roster import ROSTER

ALL_ON = {r.value: True for r in AgentRole}
SCHEDULED = {r for r, s in ROSTER.items() if s.cadence_hours is not None}


# --- the facts --------------------------------------------------------------------


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("CORP_HOME", str(tmp_path))
    monkeypatch.setenv("CORP_DATA_PATH", str(tmp_path / "data"))
    for key in ("CORP_SMTP_HOST", "CORP_SMTP_USER", "CORP_STRIPE_PAYMENT_LINK", "STRIPE_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    from corparius.config import cfg

    cfg.invalidate()
    return tmp_path


def test_a_new_company_has_none_of_them(home):
    """The state the wizard leaves behind, and the one every gate is measured against."""
    assert readiness.facts({"slug": "acme"}, str(home)) == {
        "offer": False,
        "site": False,
        "mail": False,
        "payment": False,
    }


def test_the_offer_is_read_in_both_spellings_the_company_file_uses(home):
    """`companies/example` ships `price_eur` and `product`; the wizard writes `price` and
    `description`. Reading one of each pair is how a company that *has* an offer is told it has
    none — measured on the shipped example, which fails this on `price` alone."""
    example = {"slug": "a", "offer": {"product": "Self-serve web app", "price_eur": 9}}
    assert readiness.facts(example, str(home))["offer"] is True
    wizard = {
        "slug": "a",
        "offer": {"description": "A CV rewriter for career changers.", "price": 19},
    }
    assert readiness.facts(wizard, str(home))["offer"] is True
    # A name alone is not an offer: the wizard writes `offer.name` from the company name before the
    # operator has decided anything, so this would otherwise be true on an empty company.
    assert readiness.facts({"slug": "a", "offer": {"name": "Acme"}}, str(home))["offer"] is False


def test_published_means_a_provider_accepted_it_not_that_a_folder_exists(home):
    """A site in the data folder is a draft. The marker is written by `app/publish` only after a
    provider answered, which is what makes a link worth sending to a stranger."""
    from corparius.kernel import paths

    site = paths.site_dir(str(home), "acme")
    site.mkdir(parents=True, exist_ok=True)
    (site / "index.html").write_text("<!doctype html>", encoding="utf-8")
    assert readiness.facts({"slug": "acme"}, str(home))["site"] is False, "a built site is a draft"

    (site / ".published").write_text("netlify:https://acme.example", encoding="utf-8")
    assert readiness.facts({"slug": "acme"}, str(home))["site"] is True
    assert readiness.published_url(str(home), "acme") == "https://acme.example"


def test_a_local_publish_is_a_site_without_an_address(home):
    """`local:/var/www/acme` is a real publish and not a link. The two are separate because a role
    waits on the first and a person clicks the second."""
    from corparius.kernel import paths

    site = paths.site_dir(str(home), "acme")
    site.mkdir(parents=True, exist_ok=True)
    (site / ".published").write_text("local:/var/www/acme", encoding="utf-8")
    assert readiness.facts({"slug": "acme"}, str(home))["site"] is True
    assert readiness.published_url(str(home), "acme") == ""


def test_payment_is_a_link_the_operator_pasted_or_a_key(home, monkeypatch):
    company = {"slug": "a", "offer": {"payment_link": "https://buy.stripe.com/x"}}
    assert readiness.facts(company, str(home))["payment"] is True

    monkeypatch.setenv("STRIPE_API_KEY", "sk_test_x")
    from corparius.config import cfg

    cfg.invalidate()
    assert readiness.facts({"slug": "a"}, str(home))["payment"] is True


# --- the gate ---------------------------------------------------------------------


def test_every_need_a_role_declares_is_a_fact_that_exists():
    """Both ends of the thread, the rule this project applies to every registry. A `needs` entry
    with no fact behind it would hold a role forever and never be answerable; a fact no role names
    is a measurement nothing uses."""
    declared = {need for spec in ROSTER.values() for need in spec.needs}
    assert declared <= set(readiness.FACTS), (
        f"needs nothing answers: {declared - set(readiness.FACTS)}"
    )
    assert declared, "no role declares a need, so the gate below is measuring nothing"


def test_the_four_that_are_useless_before_there_is_a_product_do_not_run():
    """The operator's own words: ads, outreach, support and finance are worth nothing until the
    company has something. Read off the roster rather than listed here twice."""
    gated = {r.value for r, s in ROSTER.items() if s.needs}
    assert gated == {"ads", "outreach", "support", "finance"}

    # A company at the start: on the clock every one of them would be due within a day.
    for hour in range(48):
        for spec in due_roles(hour, ALL_ON, ready=set()):
            assert not spec.needs, f"{spec.role.value} ran at hour {hour} with nothing to do"


def test_the_roles_that_create_the_facts_are_never_held():
    """The counterpart, and the mistake it prevents: gating design on a published site would hold
    the role that publishes it, forever. The CEO, design, strategy and the competitor watcher are
    what *produce* readiness."""
    for role in (AgentRole.CEO, AgentRole.DESIGN, AgentRole.STRATEGY, AgentRole.COMPETITOR):
        assert ROSTER[role].needs == (), f"{role.value} waits on a fact it is supposed to create"
    ran = {s.role for hour in range(24) for s in due_roles(hour, ALL_ON, ready=set())}
    assert {AgentRole.CEO, AgentRole.DESIGN, AgentRole.STRATEGY, AgentRole.COMPETITOR} <= ran


def test_each_fact_releases_exactly_what_waits_on_it():
    """One at a time, so the table is asserted rather than the total. Ads needs two, which is the
    case a single-fact test would miss."""

    def runs(ready):
        return {s.role.value for hour in range(48) for s in due_roles(hour, ALL_ON, ready=ready)}

    assert "outreach" in runs({"site"}) and "ads" not in runs({"site"})
    assert "finance" in runs({"payment"}) and "ads" not in runs({"payment"})
    assert "support" in runs({"mail"})
    assert "ads" in runs({"site", "payment"}), "ads needs both, and both is what it got"


def test_a_held_role_says_what_it_is_waiting_for():
    """ "Held" alone is a bug report. A capability that is silently never reached is the failure this
    codebase keeps finding in its own product, and a gate with no explanation would be a new one."""
    waiting = held_roles(ALL_ON, ready=set())
    assert waiting["ads"] == ["site", "payment"]
    assert waiting["outreach"] == ["site"]
    assert "ceo" not in waiting and "design" not in waiting

    assert held_roles(ALL_ON, ready={"site"})["ads"] == ["payment"]
    assert "outreach" not in held_roles(ALL_ON, ready={"site"})
    # A role the operator turned off, or paused, is not "waiting" — it is off, and saying otherwise
    # would put a fix in front of somebody who already made the decision.
    assert held_roles({**ALL_ON, "ads": False}, ready=set()).get("ads") is None
    assert held_roles(ALL_ON, ready=set(), paused={"outreach"}).get("outreach") is None


def test_passing_no_readiness_gates_nothing():
    """Every caller that only reasons about the clock, including the console's own preview of a
    day. `None` is not "nothing is ready" — the two would look identical and mean the opposite."""
    ran = {s.role.value for hour in range(48) for s in due_roles(hour, ALL_ON)}
    assert {"ads", "outreach", "support", "finance"} <= ran


# --- the day's shape --------------------------------------------------------------


def test_no_two_roles_pile_onto_hour_zero():
    """The stampede the offsets exist to end. Before them, all nine scheduled roles fired at hour 0
    and again at every multiple of 24."""
    assert {s.role for s in due_roles(0, ALL_ON)} == {AgentRole.CEO}


def test_a_day_is_spread_rather_than_bursty():
    """Measured across a full day: the busiest hour holds a small fraction of the roster, and the
    quiet hours are genuinely quiet. A budget spent evenly is a company that is still running at
    six in the evening."""
    load = [len(due_roles(hour, ALL_ON)) for hour in range(24)]
    assert max(load) <= 3, f"an hour runs {max(load)} roles: {load}"
    assert sum(load) == sum(24 // s.cadence_hours for s in ROSTER.values() if s.cadence_hours)


def test_the_new_cadences_are_the_ones_that_were_decided():
    """A ratchet, not a restatement: these numbers are a product decision with reasons written
    beside each one in `roster.py`, and a silent edit to any of them changes what a company does all
    day. Changing one here is how you declare you meant it."""
    assert {r.value: s.cadence_hours for r, s in ROSTER.items()} == {
        "ceo": 6,  # was 12: two turns a day could not answer an operator who wanted a decision
        "social": 8,  # was 2: twelve drafts a day into a queue nobody asked for
        "outreach": 6,  # was 3
        "support": 3,  # unchanged, and gated on a mailbox instead
        "ads": 24,  # was 6
        "finance": 12,  # was 6
        "strategy": 24,
        "competitor": 24,
        "design": 8,  # was 24: the role that builds what everything else points at
        "coder": None,  # on demand, and the only one
    }


def test_a_real_run_reports_what_it_held_and_why(home):
    """Through the actual runtime, on a company that has nothing yet.

    The gate has to reach the operator, and the run result is where the console already looks. A
    turn that silently never happens is the same shape of defect as a capability that is reachable
    and never reached, which this project has now found in its own product four times.

    Asserted as the **invariant** rather than as a fixed dict, and that is not caution: the CEO's
    playbook holds `set_roster` and `stop_useless_work`, so the roster it is measured against is one
    the run itself may have changed. The first version of this test named `support` and failed
    because the CEO had switched it off mid-run — which is a correct outcome wearing the shape of a
    bug, and exactly the kind of thing a literal expectation hides.
    """
    from corparius.config.settings import Settings
    from corparius.orchestrator import Runtime
    from corparius.store import Store

    settings = Settings()
    settings.llm_mock = True
    settings.data_path = str(home / "data")
    company = {
        "slug": "t",
        "name": "T",
        "offer": {},
        "agents": {r.value: True for r in AgentRole},
        "budgets": {"session_tokens": 100000, "tokens_per_minute": 100000},
    }
    store = Store(settings.data_path)
    try:
        store.save_state("t", {"tick": 0})
        done = Runtime(settings, store).run(company, ticks=6)
        acted = {row["agent"] for row in store.recent_actions("t", limit=300)}
        # The CEO can pause a role mid-run, and a role stopped by decision is not one waiting on a
        # fact. Read after the run for the same reason `agents` is: both are things the turn changes.
        stood_down = paused_roles(store, "t")
    finally:
        store.close()

    assert done["ticks_run"] == 6
    have = {f for f, ok in readiness.facts(company, settings.data_path, "t").items() if ok}
    assert not have, "the fixture company is supposed to have nothing yet"

    # Every role still enabled that needs something it does not have is named, with what it needs.
    for role, spec in ROSTER.items():
        if spec.needs and company["agents"].get(role.value) and role.value not in stood_down:
            assert done["held"].get(role.value) == list(spec.needs), (
                f"{role.value} is enabled and unfed, and the run did not say so"
            )
    assert done["held"], "nothing was held on a company with nothing: the gate did not run"
    assert "ceo" not in done["held"] and "design" not in done["held"]

    # And the other end: none of the gated roles spent a turn. The log is what the operator pays
    # for, so it is what the claim is checked against.
    assert not acted & {"ads", "outreach", "support", "finance"}, acted


def test_a_filed_task_outranks_the_gate(home):
    """The other half of the gate, and not a softening of it.

    A role can be held because the company has nothing for it yet. A task filed against that role is
    somebody having decided otherwise — the CEO through `create_tasks`, or the operator through the
    backlog — and work that silently never runs is the same defect this gate exists to prevent,
    arriving from the other side. Found by `test_backlog_task_runs_the_real_tool`, which stopped
    passing the moment outreach started waiting for a site.

    It outranks the **gate** and not the **clock**: the role runs on its own hour, because that is
    what paces the whole roster and a task is not an interrupt.
    """
    from corparius.store import Store

    store = Store(str(home / "data"))
    try:
        assert store.roles_with_approved_work("t") == set()
        # (company, title, target): the argument order bit once already, and reading it back is
        # what turns "the call succeeded" into "the row says what I meant".
        store.add_task("t", "Email the three warm ones", "outreach", tool="send_outreach")
        assert {row["target"] for row in store.list_tasks("t")} == {"outreach"}
        assert store.roles_with_approved_work("t") == {"outreach"}
    finally:
        store.close()

    # Held with nothing filed; scheduled with something filed, on its own hour either way.
    hours = range(48)
    without = {s.role.value for h in hours for s in due_roles(h, ALL_ON, ready=set())}
    assert "outreach" not in without
    with_work = {
        s.role.value
        for h in hours
        for s in due_roles(h, ALL_ON, ready=set(), has_work={"outreach"})
    }
    assert "outreach" in with_work
    assert "ads" not in with_work, "only the role the work was filed against"

    # And it stops calling itself held, because it is not: it is about to run.
    assert "outreach" not in held_roles(ALL_ON, ready=set(), has_work={"outreach"})
    assert held_roles(ALL_ON, ready=set(), has_work={"outreach"})["ads"] == ["site", "payment"]


def test_an_offer_that_is_not_a_mapping_is_not_an_offer(home):
    """`offer:` left as a string or a list in a hand-edited company file. Reading `.get` off it
    would raise inside the scheduler, which runs every tick, so the shape is checked rather than
    trusted."""
    for broken in ("just a sentence", ["a", "b"], 42):
        assert readiness.facts({"slug": "a", "offer": broken}, str(home))["offer"] is False


def test_a_marker_that_cannot_be_read_is_no_address_rather_than_a_crash(home, monkeypatch):
    """The site is published (the marker exists) and the file itself will not open: a permission
    change, a half-written file, a folder synced by something else. The fact stays true and the
    address is empty, because the scheduler must not fall over on a read it does not depend on."""
    from corparius.kernel import paths

    site = paths.site_dir(str(home), "acme")
    site.mkdir(parents=True, exist_ok=True)
    (site / ".published").write_text("netlify:https://acme.example", encoding="utf-8")

    def refuse(*_a, **_kw):
        raise OSError("permission denied")

    monkeypatch.setattr(pathlib.Path, "read_text", refuse)
    assert readiness.published_url(str(home), "acme") == ""
    assert readiness.facts({"slug": "acme"}, str(home))["site"] is True
