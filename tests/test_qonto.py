"""Qonto, the other way a French company is paid.

Stripe is a checkout link a stranger clicks. Qonto is a business account a client transfers to
against an invoice, which is how business-to-business selling works here. Both mean "this company
can take money", and a utility gate that only knew about checkout links held the finance agent
forever on exactly the company that had the other one.

**Read-only, and that is a decision rather than a first cut.** `send_financial_transaction` already
sits at the human gate for Stripe; adding a second provider that can move money is a change to make
on its own, with its own approval path, not inside a settings addition.

**And no claim about the French e-invoicing mandate.** From 2026 a business must be able to receive
electronic invoices and the obligation reaches everybody in 2027, with transmission through an
approved platform. Whether a given bank is on that register is a fact about a public list rather
than about this code, so nothing here asserts it: `docs/conformite-fr.md` holds the obligation and
the `legal:` block holds the identifiers an invoice has to carry.
"""

import pathlib

import pytest

from corparius.providers import qonto


@pytest.fixture
def clean(monkeypatch, tmp_path):
    monkeypatch.setenv("CORP_HOME", str(tmp_path))
    for key in ("QONTO_LOGIN", "QONTO_SECRET_KEY", "STRIPE_API_KEY", "CORP_STRIPE_PAYMENT_LINK"):
        monkeypatch.delenv(key, raising=False)
    from corparius.config import cfg

    cfg.invalidate()
    return monkeypatch


class _Answer:
    def __init__(self, status=200, body=None, bad_json=False):
        self.status_code = status
        self._body = body or {}
        self._bad = bad_json

    def json(self):
        if self._bad:
            raise ValueError("not json")
        return self._body


def _set(monkeypatch, login="acme", secret="s3cret"):
    monkeypatch.setenv("QONTO_LOGIN", login)
    monkeypatch.setenv("QONTO_SECRET_KEY", secret)
    from corparius.config import cfg

    cfg.invalidate()


def test_nothing_configured_says_where_to_find_the_keys(clean):
    """A provider that answers "not configured" and stops there sends an operator hunting. The two
    values are in one screen of the Qonto app, so the refusal names it."""
    out = qonto.check()
    assert out["ok"] is False and out["configured"] is False
    assert "API keys" in out["detail"] or "clés API" in out["detail"]
    assert qonto.configured() is False


def test_the_credentials_are_proved_by_a_read_and_nothing_else(clean, monkeypatch):
    """One GET, on the organization. The assertion that matters is the **method**: a check that
    created something to prove it could would be a check nobody dares run twice."""
    seen = {}

    def fake_get(url, headers=None, timeout=None, params=None):
        seen["url"] = url
        seen["auth"] = (headers or {}).get("Authorization")
        # A check has no query string. Asserted rather than ignored: `_get` takes params now, and a
        # helper that started attaching a default filter to every read would change what "prove the
        # credentials" means without anything saying so.
        seen["params"] = params
        return _Answer(body={"organization": {"slug": "acme-sas", "bank_accounts": [{}, {}]}})

    _set(monkeypatch)
    monkeypatch.setattr(qonto.requests, "get", fake_get)
    monkeypatch.setattr(
        qonto.requests, "post", lambda *a, **k: pytest.fail("a check must not write")
    )

    out = qonto.check()
    assert out["ok"] is True and out["accounts"] == 2 and out["organization"] == "acme-sas"
    assert seen["url"].endswith("/organization")
    assert seen["auth"] == "acme:s3cret"
    assert seen["params"] is None


@pytest.mark.parametrize("status", [401, 403])
def test_rejected_credentials_say_so_rather_than_looking_unreachable(clean, monkeypatch, status):
    """The two failures an operator confuses. "Qonto is down" and "Qonto refused your key" want
    different actions, and reporting the second as the first sends them to a status page."""
    _set(monkeypatch)
    monkeypatch.setattr(qonto.requests, "get", lambda *a, **k: _Answer(status=status))
    out = qonto.check()
    assert out["ok"] is False and out["configured"] is True
    assert "rejected" in out["detail"] or "rejeté" in out["detail"]


def test_a_network_failure_is_not_a_rejection(clean, monkeypatch):
    _set(monkeypatch)

    def boom(*a, **k):
        raise qonto.requests.RequestException("no route to host")

    monkeypatch.setattr(qonto.requests, "get", boom)
    out = qonto.check()
    assert out["ok"] is False and out["configured"] is True
    assert "no route to host" in out["detail"]


def test_an_answer_that_is_not_json_is_reported_rather_than_raised(clean, monkeypatch):
    """A captive portal and a proxy error page both return 200 with HTML. Raising here would take
    down the settings screen the operator is standing on."""
    _set(monkeypatch)
    monkeypatch.setattr(qonto.requests, "get", lambda *a, **k: _Answer(bad_json=True))
    assert qonto.check()["ok"] is False


def test_the_message_follows_the_language_the_operator_reads(clean, monkeypatch):
    _set(monkeypatch)
    monkeypatch.setattr(qonto.requests, "get", lambda *a, **k: _Answer(status=401))
    assert "rejeté" in qonto.check(lang="fr")["detail"]


# --- what it changes for the roster -----------------------------------------------


def test_a_qonto_account_is_a_company_that_can_be_paid(clean, monkeypatch, tmp_path):
    """The point of adding it to the settings at all. Without this the gate holds the finance agent
    on a company that invoices its clients and is paid by transfer, which is most French
    business-to-business selling."""
    from corparius import readiness

    assert readiness.facts({"slug": "acme"}, str(tmp_path))["payment"] is False
    _set(monkeypatch)
    assert readiness.facts({"slug": "acme"}, str(tmp_path))["payment"] is True


def test_half_the_pair_is_not_an_account(clean, monkeypatch):
    """A login with no secret is somebody half way through the setup screen, and calling that
    "can be paid" would release the finance agent onto credentials that cannot authenticate."""
    from corparius import readiness

    monkeypatch.setenv("QONTO_LOGIN", "acme")
    from corparius.config import cfg

    cfg.invalidate()
    assert readiness.facts({"slug": "acme"}, ".")["payment"] is False
    assert qonto.configured() is False


# --- what came in, which is the half that makes the role worth running -------------


def _org(accounts):
    return {"organization": {"slug": "acme", "bank_accounts": accounts}}


def _routed(monkeypatch, org, transactions, seen=None):
    """One fake for both calls, dispatching on the path. `reconcile` reads the organization and then
    the transactions, so a single-answer double would make the second read return an account list
    and quietly report zero."""

    def fake_get(url, headers=None, timeout=None, params=None):
        if seen is not None:
            seen.setdefault("params", []).append(params)
            seen.setdefault("urls", []).append(url)
        if url.endswith("/organization"):
            return _Answer(body=org)
        return _Answer(body={"transactions": transactions})

    monkeypatch.setattr(qonto.requests, "get", fake_get)
    monkeypatch.setattr(
        qonto.requests, "post", lambda *a, **k: pytest.fail("a reconcile must not write")
    )


def test_a_reconcile_reports_what_landed_and_the_balance(clean, monkeypatch):
    """The number the finance role exists to know. Two accounts, so the balance is a sum rather than
    a first row, which is the shape a company with a current and a savings account has."""
    _set(monkeypatch)
    _routed(
        monkeypatch,
        # Deliberately four numbers that share no sum: a balance and an income that happened to be
        # equal would let a swapped pair of keys pass this.
        _org([{"id": "a1", "balance": 1200.5}, {"id": "a2", "balance": 300}]),
        [
            {"amount": 480, "status": "completed", "label": "MAIRIE DE LYON"},
            {"amount": 120.25, "status": "completed", "label": "CABINET NORD"},
        ],
    )

    out = qonto.reconcile()
    assert out["ok"] is True
    assert out["balance_eur"] == 1500.5, "the balance is a sum over accounts, not the first row"
    # Both accounts are read, so the same two transactions come back twice: what this asserts is
    # that the arithmetic sums what it was given, not that Qonto would send it twice.
    assert out["transfers"] == 4 and out["received_eur"] == 1200.5
    assert "MAIRIE DE LYON" in out["detail"]


def test_a_transaction_still_processing_is_not_money_the_company_has(clean, monkeypatch):
    """Optimism in a reconcile is worse than silence. A pending transfer counted as received makes
    the figure wrong in exactly the month an operator is deciding whether they can pay themselves."""
    _set(monkeypatch)
    _routed(
        monkeypatch,
        _org([{"id": "a1", "balance": 0}]),
        [
            {"amount": 500, "status": "pending", "label": "NOT YET"},
            {"amount": 40, "status": "completed", "label": "LANDED"},
        ],
    )

    out = qonto.reconcile()
    assert out["received_eur"] == 40 and out["transfers"] == 1
    assert "NOT YET" not in out["detail"]


def test_a_row_with_an_unreadable_amount_does_not_take_the_reconcile_down(clean, monkeypatch):
    """One odd row tells the operator nothing about the other ninety-nine, so it is worth zero and
    not an exception. This runs unattended: an uncaught `ValueError` here is a finance turn that
    reports a crash instead of a figure."""
    _set(monkeypatch)
    _routed(
        monkeypatch,
        _org([{"id": "a1", "balance": None}]),
        [
            {"amount": "not-a-number", "status": "completed", "label": "ODD"},
            {"amount": 10, "status": "completed", "label": "FINE"},
        ],
    )

    out = qonto.reconcile()
    assert out["ok"] is True and out["received_eur"] == 10 and out["balance_eur"] == 0


def test_the_reconcile_asks_for_credits_inside_the_window(clean, monkeypatch):
    """The ceilings are the reason this is safe to run unattended twice a day. Asserted on the query
    rather than trusted: an account with four years of history would otherwise be paged through in
    full to answer a question about last month."""
    seen: dict = {}
    _set(monkeypatch)
    _routed(monkeypatch, _org([{"id": "a1", "balance": 0}]), [], seen)

    qonto.reconcile(days=7)
    query = seen["params"][1]
    assert query["side"] == "credit", (
        "a reconcile that counted debits would report a net, not income"
    )
    assert query["per_page"] == qonto.MAX_ROWS
    assert query["bank_account_id"] == "a1"
    assert query["settled_at_from"].endswith("Z"), query["settled_at_from"]


def test_an_organization_with_no_account_says_so_rather_than_reporting_zero(clean, monkeypatch):
    """Zero euros received and "there is no account to look at" are different facts, and the second
    one is an operator's problem to fix. Reporting the first would hide it behind a plausible
    number."""
    _set(monkeypatch)
    _routed(monkeypatch, _org([]), [])

    out = qonto.reconcile()
    assert out["ok"] is False and out["configured"] is True
    assert "no bank account" in out["detail"] or "sans compte" in out["detail"]


def test_a_refused_credential_fails_the_reconcile_instead_of_reporting_nothing(clean, monkeypatch):
    """The failure that matters most, because it is silent otherwise: a revoked key answers 401, and
    a reconcile that swallowed it would report zero income and be believed."""
    _set(monkeypatch)
    monkeypatch.setattr(
        qonto.requests, "get", lambda *a, **k: _Answer(status=401, body={"errors": []})
    )
    out = qonto.reconcile()
    assert out["ok"] is False and out["configured"] is True
    assert "rejected" in out["detail"] or "rejeté" in out["detail"]


def test_nothing_connected_is_not_a_failed_read(clean):
    """No credentials is `configured: False`, which is how the console tells "you have not set this
    up" apart from "this is set up and broken"."""
    out = qonto.reconcile()
    assert out["ok"] is False and out["configured"] is False


# --- and what a visitor is told ----------------------------------------------------


def test_a_company_paid_by_transfer_says_so_on_its_own_page(clean, monkeypatch, tmp_path):
    """The hole this closed. An invoiced business had a page whose only call to action was "talk to
    us" and which said nothing about the transaction, so a visitor could not tell a quote from a
    demo from a shop that was broken. Being ready to be paid and having no way to say it is half a
    product."""
    from corparius.sitegen.build import build_site

    company = {
        "slug": "acme",
        "name": "Acme",
        "language": "fr",
        "offer": {"product": "Audit trimestriel", "price_eur": 2400},
    }
    before = pathlib.Path(build_site(company, str(tmp_path / "a"))).read_text(encoding="utf-8")
    assert "sur facture" not in before, "the chip appeared without an account connected"

    _set(monkeypatch)
    after = pathlib.Path(build_site(company, str(tmp_path / "b"))).read_text(encoding="utf-8")
    assert "Paiement sur facture, par virement" in after


def test_a_checkout_link_wins_and_the_page_makes_one_claim(clean, monkeypatch, tmp_path):
    """Both configured is the case the operator asked for, and a page that advertised two payment
    routes would be a page that has not decided how it sells. The checkout is the stronger offer
    wherever it exists, so it is the one a stranger sees."""
    from corparius.sitegen.build import build_site

    _set(monkeypatch)
    monkeypatch.setenv("CORP_STRIPE_PAYMENT_LINK", "https://buy.stripe.com/x")
    from corparius.config import cfg

    cfg.invalidate()
    company = {
        "slug": "acme",
        "name": "Acme",
        "language": "fr",
        "offer": {"product": "Audit", "price_eur": 2400, "billing": "stripe"},
    }
    page = pathlib.Path(build_site(company, str(tmp_path / "c"))).read_text(encoding="utf-8")

    assert "buy.stripe.com" in page, "the checkout link never reached the button"
    assert "sur facture" not in page, "the page made two payment claims at once"


# --- the tool the finance role runs ------------------------------------------------


def test_the_finance_role_can_actually_reach_a_bank(clean):
    """The gate said this company could be paid and the role had nothing but Stripe tools, so it ran
    twice a day and produced nothing. That is the exact shape the utility gate was built to stop,
    reintroduced by widening the gate without widening the playbook."""
    from corparius.kernel.records import AgentRole
    from corparius.roster import ROSTER
    from corparius.tools.registry import TOOLS

    assert "reconcile_qonto" in ROSTER[AgentRole.FINANCE].playbook
    assert "reconcile_qonto" in TOOLS, "in a playbook and not in the registry is a turn that raises"


def test_an_unreachable_bank_is_a_failure_and_never_an_invented_figure(clean, monkeypatch):
    """The property that matters more than the number.

    `reconcile_stripe` falls back to "MRR 27 EUR, 3 active subs (mock)" when the provider says
    nothing, and that is survivable for a demo. It is not survivable here: this figure feeds the KPI
    review, which feeds the CEO's decisions, and this file already carries the story of two invented
    numbers doing exactly that. A number about money is measured or it is absent.
    """
    import types

    from corparius.tools.registry import TOOLS

    _set(monkeypatch)
    monkeypatch.setattr(qonto.requests, "get", lambda *a, **k: _Answer(status=503))
    ctx = types.SimpleNamespace(company={"slug": "acme", "language": "fr"})

    result = TOOLS["reconcile_qonto"].run(ctx)
    assert result.ok is False, "an unreachable bank was reported as a successful reconcile"
    assert "503" in result.output
    for invented in ("27", "MRR", "mock"):
        assert invented not in result.output


def test_no_account_connected_is_reported_without_reaching_the_network(clean, monkeypatch):
    """A company with no bank should not produce a request, and the message has to say which of the
    two things is wrong: not connected, or connected and broken."""
    import types

    from corparius.tools.registry import TOOLS

    monkeypatch.setattr(
        qonto.requests, "get", lambda *a, **k: pytest.fail("asked a bank that was never connected")
    )
    ctx = types.SimpleNamespace(company={"slug": "acme", "language": "fr"})
    result = TOOLS["reconcile_qonto"].run(ctx)
    assert result.ok is False and "Aucun compte Qonto" in result.output
