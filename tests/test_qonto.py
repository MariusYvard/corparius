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

    def fake_get(url, headers=None, timeout=None):
        seen["url"] = url
        seen["auth"] = (headers or {}).get("Authorization")
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
