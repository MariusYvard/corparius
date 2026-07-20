"""Reading the mailbox, and the return leg of prospecting: knowing who replied.

The company emails prospects; without this it never learns whether anyone
answered, which is the one signal it exists to chase.
"""

import types

from app import cfg, mailbox, tools
from app.store import Store


def test_unconfigured_mailbox_is_an_empty_layer_not_a_crash(monkeypatch):
    monkeypatch.delenv("CORP_IMAP_HOST", raising=False)
    cfg.invalidate()
    assert mailbox.configured() is False
    assert mailbox.fetch() == []
    result = mailbox.check()
    assert result["ok"] is False and result["configured"] is False
    assert "mock" in result["detail"]


def test_triage_says_it_is_using_samples_when_no_mailbox(monkeypatch):
    monkeypatch.delenv("CORP_IMAP_HOST", raising=False)
    cfg.invalidate()
    ctx = types.SimpleNamespace(company={"name": "X", "slug": "x"})
    out = tools._triage_inbox(ctx)
    # The old version claimed "3 support, 1 sales, 0 urgent" as if it had looked.
    assert "no mailbox connected" in out and "sample" in out


def test_triage_reads_a_real_inbox(monkeypatch):
    monkeypatch.setenv("CORP_IMAP_HOST", "imap.example.test")
    cfg.invalidate()
    monkeypatch.setattr(
        mailbox,
        "fetch",
        lambda **kw: [
            mailbox.Message(
                sender="ann@corp.test",
                sender_name="Ann",
                subject="URGENT: refund please",
                body="I want a refund",
            ),
            mailbox.Message(sender="bob@corp.test", subject="question", body="how does it work"),
        ],
    )
    ctx = types.SimpleNamespace(company={"name": "X", "slug": "x"})
    out = tools._triage_inbox(ctx)
    assert "2 unread" in out and "1 look urgent" in out and "Ann" in out


def test_replies_are_matched_to_the_outreach_that_caused_them(tmp_path, monkeypatch):
    monkeypatch.setenv("CORP_IMAP_HOST", "imap.example.test")
    cfg.invalidate()
    store = Store(str(tmp_path))
    store.record_outreach("x", "Lead@Corp.test", "<mid-1>", "hello")
    store.record_outreach("x", "silent@corp.test", "<mid-2>", "hello")
    assert store.outreach_stats("x") == {"sent": 2, "replied": 0, "reply_rate": 0.0}

    monkeypatch.setattr(
        mailbox,
        "fetch",
        lambda **kw: [
            mailbox.Message(sender="lead@corp.test", subject="Re: hello", body="Yes, interested."),
            mailbox.Message(sender="stranger@nowhere.test", subject="spam", body="buy this"),
        ],
    )
    ctx = types.SimpleNamespace(company={"name": "X", "slug": "x"}, store=store)
    out = tools._scan_replies(ctx)

    assert "1 prospect(s) replied" in out and "lead@corp.test" in out
    stats = store.outreach_stats("x")
    assert stats["sent"] == 2 and stats["replied"] == 1
    # The address is matched case-insensitively: we stored it lowercased.
    assert "silent@corp.test" in store.pending_outreach("x")
    assert "lead@corp.test" not in store.pending_outreach("x")


def test_a_reply_is_only_counted_once(tmp_path, monkeypatch):
    monkeypatch.setenv("CORP_IMAP_HOST", "imap.example.test")
    cfg.invalidate()
    store = Store(str(tmp_path))
    store.record_outreach("x", "lead@corp.test", "<mid-1>", "hello")
    monkeypatch.setattr(
        mailbox,
        "fetch",
        lambda **kw: [mailbox.Message(sender="lead@corp.test", subject="Re: hello", body="yes")],
    )
    ctx = types.SimpleNamespace(company={"name": "X", "slug": "x"}, store=store)
    tools._scan_replies(ctx)
    second = tools._scan_replies(ctx)
    # The same unread message is still there on the next tick; the reply rate
    # must not climb every time the agent looks at it.
    assert store.outreach_stats("x")["replied"] == 1
    assert "No outreach awaiting a reply" in second


def test_scan_replies_says_when_no_mailbox_is_connected(tmp_path, monkeypatch):
    monkeypatch.delenv("CORP_IMAP_HOST", raising=False)
    cfg.invalidate()
    store = Store(str(tmp_path))
    ctx = types.SimpleNamespace(company={"name": "X", "slug": "x"}, store=store)
    assert "No mailbox connected" in tools._scan_replies(ctx)


def test_outreach_records_who_it_wrote_to(tmp_path, monkeypatch):
    from app import integrations
    from app.leadsource import Lead

    store = Store(str(tmp_path))
    monkeypatch.setattr(
        integrations, "send_email_tracked", lambda to, subject, body: ("sent", f"<{to}>")
    )
    ctx = types.SimpleNamespace(
        company={"name": "X", "slug": "x"}, store=store, leads=[Lead(email="a@x.test")]
    )
    tools._send_outreach(ctx, "hello")
    pending = store.pending_outreach("x")
    assert "a@x.test" in pending
