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


def send_outreach_email(company: dict, draft: str, timeout: int = 15) -> str | None:
    """Send the drafted opener over SMTP to a test/notification address. Set
    CORP_SMTP_HOST and CORP_OUTREACH_TEST_TO (plus auth if your relay needs it)."""
    host = os.environ.get("CORP_SMTP_HOST", "")
    to = os.environ.get("CORP_OUTREACH_TEST_TO", "")
    if not host or not to:
        return None
    try:
        msg = EmailMessage()
        msg["Subject"] = f"{company.get('name', 'corparius')} outreach"
        msg["From"] = os.environ.get("CORP_SMTP_FROM") or os.environ.get("CORP_SMTP_USER", "corparius@localhost")
        msg["To"] = to
        msg.set_content(draft or "Outreach draft")
        with smtplib.SMTP(host, int(os.environ.get("CORP_SMTP_PORT", "587")), timeout=timeout) as s:
            s.starttls()
            user = os.environ.get("CORP_SMTP_USER", "")
            if user:
                s.login(user, os.environ.get("CORP_SMTP_PASSWORD", ""))
            s.send_message(msg)
        return f"Outreach email sent to {to} via SMTP (live)"
    except (OSError, smtplib.SMTPException, ValueError):
        return None
