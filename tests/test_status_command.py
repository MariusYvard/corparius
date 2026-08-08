"""What a terminal can now say about a company, and the shapes I got wrong writing it.

`corparius status` printed four numbers: actions, tokens, pending approvals, and a count per
agent. The console polled a payload with the flow — work in progress, what is waiting, which
role is the bottleneck — the session budget, the money, and whether a run was going. An
operator on a headless box had the cheapest half of what the product already knew.

The barrier was `state.runs.get(slug, {})`, a dict in the console's process. It is a parameter
now, exactly as the chat's history is.

**Every field is asserted against a real payload**, because the first version of the command was
written against an imagined one: it read `flow["done"]` and `status["cost"]`, and neither exists.
The real names are `throughput` and a per-agent `spend_by_agent` list, with `cost_reported` as a
separate boolean — which is not pedantry, it is the distinction between "not reported" and
"free".
"""

import pytest

from corparius.app import overview
from corparius.config.settings import Settings
from corparius.store import Store

COMPANY = {"slug": "acme", "name": "Acme", "offer": {"product": "p"}, "agents": {"ceo": True}}


@pytest.fixture()
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("CORP_HOME", str(tmp_path))
    monkeypatch.setenv("CORP_DATA_PATH", str(tmp_path / "data"))
    (tmp_path / "companies" / "acme").mkdir(parents=True)
    (tmp_path / "companies" / "acme" / "company.yaml").write_text(
        "name: Acme\nslug: acme\noffer:\n  product: p\n", encoding="utf-8"
    )
    from corparius.config import cfg

    cfg.invalidate()
    return tmp_path


@pytest.fixture()
def store(home):
    s = Store(str(home / "data"))
    yield s
    s.close()


# --- the seam -------------------------------------------------------------------


def test_it_takes_no_console_object(store):
    """The reason this moved, and the third time the same parameter was the whole barrier —
    after `persist`'s UiState and `chat`'s history."""
    import inspect

    params = list(inspect.signature(overview.build).parameters)
    assert params[:3] == ["store", "settings", "slug"]
    assert "state" not in params


def test_a_caller_with_no_run_gets_a_company_at_rest(store, home):
    """A one-shot command has no in-flight run, and saying so is the truth rather than a
    degraded answer."""
    data = overview.build(store, Settings(), "acme", company=COMPANY)
    assert data["ok"] is True
    assert data["running"] is False


def test_a_caller_that_has_one_says_so(store, home):
    """What the console passes. The service does not know where it came from."""
    data = overview.build(
        store, Settings(), "acme", company=COMPANY, run={"running": True, "loop": True}
    )
    assert data["running"] is True and data["loop"] is True


# --- the fields the command reads, asserted against a real payload --------------


@pytest.mark.parametrize(
    "field", ["status", "flow", "tick", "session_budget", "spend_by_agent", "cost_reported"]
)
def test_the_payload_carries_what_the_command_prints(store, home, field):
    """Named one by one so a rename fails here rather than in a KeyError on somebody's
    terminal — which is how the first version of the command was found."""
    assert field in overview.build(store, Settings(), "acme", company=COMPANY)


def test_the_flow_is_named_throughput_not_done(store, home):
    """The exact mistake: I wrote `flow["done"]`. The store calls it `throughput`, and it counts
    completed work rather than the `done` column's length."""
    flow = overview.build(store, Settings(), "acme", company=COMPANY)["flow"]
    assert "throughput" in flow and "done" not in flow
    for expected in ("wip", "waiting", "blocked", "bottleneck"):
        assert expected in flow


def test_money_is_per_agent_and_reported_separately(store, home):
    """`status` has no `cost`. Spend is a list per agent, and whether *anything* reported money
    is its own boolean — because a provider that says nothing must read as "not reported" and
    never as free. That distinction is documented in migration 5 and it survives here."""
    store.record_usage("acme", "ceo", 10, 5, cost=0.0)
    data = overview.build(store, Settings(), "acme", company=COMPANY)
    assert data["cost_reported"] is False
    rows = data["spend_by_agent"]
    assert rows and set(rows[0]) >= {"agent", "t", "cost"}


def test_a_reported_cost_flips_the_flag(store, home):
    store.record_usage("acme", "ceo", 10, 5, cost=0.0004)
    assert overview.build(store, Settings(), "acme", company=COMPANY)["cost_reported"] is True


# --- the command ----------------------------------------------------------------


def test_the_command_prints_the_flow_and_the_budget(home, capsys):
    from corparius import cli

    assert cli.main(["status", "--company", "acme"]) == 0
    said = capsys.readouterr().out
    assert "flow:" in said and "bottleneck" not in said, "no work yet, so no bottleneck"
    assert "of " in said, "tokens have to be shown against the session budget"
    assert "money:" in said


def test_the_command_says_not_reported_rather_than_zero(home, capsys):
    """A company that has spent nothing and a provider that reports nothing look identical in a
    number and are different facts."""
    from corparius import cli

    cli.main(["status", "--company", "acme"])
    assert "money:   not reported" in capsys.readouterr().out


def test_the_command_can_print_the_whole_payload(home, capsys):
    """What a script wants, and what the console gets — the same object, so a script cannot be
    told less than the page."""
    import json

    from corparius import cli

    assert cli.main(["status", "--company", "acme", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["ok"] is True and "flow" in data and "approvals" in data


def test_the_command_names_a_pending_approval(home, capsys):
    """The one thing in the payload that is a decision waiting on a person. Printing the count
    without saying which command shows them would be a dead end."""
    from corparius import cli
    from corparius.kernel.records import ApprovalRequest

    store = Store(str(home / "data"))
    store.add_approval(
        ApprovalRequest(
            id="a1",
            company="acme",
            agent="finance",
            tool="send_financial_transaction",
            parameters={},
            status="pending",
        )
    )
    store.close()
    cli.main(["status", "--company", "acme"])
    said = capsys.readouterr().out
    assert "waiting on you: 1 approval" in said and "corparius approvals" in said
