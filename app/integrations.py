"""Real backends for the business tools. Each function returns a result string
when its integration is configured, or None so the calling tool falls back to
its mock effect. Nothing here runs unless the matching environment variables are
set, so the whole system still works offline out of the box.
"""
from __future__ import annotations
import os
import smtplib
from email.message import EmailMessage

import requests

from . import deliverability


def stripe_reconcile(timeout: int = 15) -> str | None:
    """Live Stripe balance read. Set STRIPE_API_KEY (a restricted read key)."""
    key = os.environ.get("STRIPE_API_KEY", "")
    if not key:
        return None
    try:
        r = requests.get("https://api.stripe.com/v1/balance",
                         headers={"Authorization": f"Bearer {key}"}, timeout=timeout)
        r.raise_for_status()
        avail = (r.json().get("available") or [{}])[0]
        amount = avail.get("amount", 0) / 100
        currency = (avail.get("currency", "") or "").upper()
        return f"Stripe reconciled: available {amount:.2f} {currency} (live)"
    except (requests.RequestException, ValueError, IndexError, KeyError):
        return None


def send_email(to: str, subject: str, body: str, timeout: int = 15) -> str | None:
    """Send one email over SMTP, gated by the deliverability guard. Returns None
    when SMTP is not configured (so the caller falls back), else "sent",
    "skipped (reason)" or "error"."""
    host = os.environ.get("CORP_SMTP_HOST", "")
    if not host or not to:
        return None
    ok, reason = deliverability.can_send(to)
    if not ok:
        return f"skipped ({reason})"
    try:
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = os.environ.get("CORP_SMTP_FROM") or os.environ.get("CORP_SMTP_USER", "corparius@localhost")
        msg["To"] = to
        msg.set_content(body or "")
        with smtplib.SMTP(host, int(os.environ.get("CORP_SMTP_PORT", "587")), timeout=timeout) as s:
            s.starttls()
            user = os.environ.get("CORP_SMTP_USER", "")
            if user:
                s.login(user, os.environ.get("CORP_SMTP_PASSWORD", ""))
            s.send_message(msg)
        deliverability.record_send()
        return "sent"
    except (OSError, smtplib.SMTPException, ValueError):
        return "error"


def send_outreach_email(company: dict, draft: str) -> str | None:
    """Fallback path: send the opener to a single test/notification address
    (CORP_OUTREACH_TEST_TO). Used when no real leads are available."""
    to = os.environ.get("CORP_OUTREACH_TEST_TO", "")
    if not to:
        return None
    res = send_email(to, f"{company.get('name', 'corparius')} outreach", draft)
    if res is None:
        return None
    if res == "sent":
        return f"Outreach email sent to {to} via SMTP (live)"
    return f"Outreach {res} for {to}"
