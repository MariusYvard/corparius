"""Integrations must stay dormant until configured, so the system runs offline."""

from corparius import integrations


def test_stripe_is_dormant_without_a_key(monkeypatch):
    monkeypatch.delenv("STRIPE_API_KEY", raising=False)
    assert integrations.stripe_reconcile() is None


def test_outreach_is_dormant_without_smtp(monkeypatch):
    monkeypatch.delenv("CORP_SMTP_HOST", raising=False)
    monkeypatch.delenv("CORP_OUTREACH_TEST_TO", raising=False)
    assert integrations.send_outreach_email({"name": "X"}, "hi") is None
