"""Outreach must email the leads found in the same turn, honour the per-run cap,
and fall back cleanly when there are no leads."""
import types

from app import tools, integrations
from app.leadsource import Lead


def _fake_send(calls):
    # Outreach sends through send_email_tracked, which also hands back the
    # Message-ID so a later reply can be tied to the mail that caused it.
    return lambda to, subject, body: (calls.append(to) or ("sent", f"<{to}>"))


def test_sends_to_found_leads(monkeypatch):
    calls = []
    monkeypatch.setattr(integrations, "send_email_tracked", _fake_send(calls))
    ctx = types.SimpleNamespace(company={"name": "X"},
                                leads=[Lead(email="a@x.com"), Lead(email="b@x.com")])
    out = tools._send_outreach(ctx, "hello")
    assert calls == ["a@x.com", "b@x.com"]
    assert "2 sent" in out


def test_falls_back_without_leads(monkeypatch):
    monkeypatch.setattr(integrations, "send_outreach_email", lambda company, draft: None)
    ctx = types.SimpleNamespace(company={"name": "X"}, leads=[])
    assert "Cold email sent" in tools._send_outreach(ctx, "opener text")


def test_respects_per_run_cap(monkeypatch):
    calls = []
    monkeypatch.setattr(integrations, "send_email_tracked", _fake_send(calls))
    monkeypatch.setenv("CORP_OUTREACH_MAX_PER_RUN", "1")
    ctx = types.SimpleNamespace(company={"name": "X"},
                                leads=[Lead(email="a@x.com"), Lead(email="b@x.com")])
    tools._send_outreach(ctx, "hi")
    assert calls == ["a@x.com"]
