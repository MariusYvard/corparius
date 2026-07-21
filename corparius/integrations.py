"""Real backends for the business tools. Each function returns a result string
when its integration is configured, or None so the calling tool falls back to
its mock effect. Nothing here runs unless the matching environment variables are
set, so the whole system still works offline out of the box.
"""

from __future__ import annotations

import smtplib
import socket
import ssl
from email.message import EmailMessage
from email.utils import make_msgid

import requests

from . import cfg, deliverability, i18n


def stripe_reconcile(timeout: int = 15) -> str | None:
    """Live Stripe balance read. Set STRIPE_API_KEY (a restricted read key)."""
    key = cfg.get("STRIPE_API_KEY", "")
    if not key:
        return None
    try:
        r = requests.get(
            "https://api.stripe.com/v1/balance",
            headers={"Authorization": f"Bearer {key}"},
            timeout=timeout,
        )
        r.raise_for_status()
        avail = (r.json().get("available") or [{}])[0]
        amount = avail.get("amount", 0) / 100
        currency = (avail.get("currency", "") or "").upper()
        return f"Stripe reconciled: available {amount:.2f} {currency} (live)"
    except (requests.RequestException, ValueError, IndexError, KeyError):
        return None


def stripe_payments(limit: int = 8, timeout: int = 15) -> dict:
    """Received payments. Live when STRIPE_API_KEY is set (read-only charges
    list), otherwise a deterministic mock so the console always has something
    honest to show."""
    key = cfg.get("STRIPE_API_KEY", "").strip()
    if key:
        try:
            r = requests.get(
                "https://api.stripe.com/v1/charges",
                params={"limit": limit},
                auth=(key, ""),
                timeout=timeout,
            )
            r.raise_for_status()
            items = [
                {
                    "amount": c.get("amount", 0) / 100.0,
                    "currency": (c.get("currency") or "eur").upper(),
                    "status": c.get("status", ""),
                    "paid": bool(c.get("paid")),
                    "description": c.get("description")
                    or c.get("billing_details", {}).get("name")
                    or "",
                    "ts": c.get("created", 0),
                }
                for c in r.json().get("data", [])
            ]
            total = sum(i["amount"] for i in items if i["paid"])
            return {"source": "stripe", "payments": items, "total_paid": round(total, 2)}
        except requests.RequestException as exc:
            return {"source": "error", "payments": [], "total_paid": 0.0, "error": str(exc)}
    mock = [
        {
            "amount": 9.0,
            "currency": "EUR",
            "status": "succeeded",
            "paid": True,
            "description": "CV optimisation, single",
            "ts": 0,
        },
        {
            "amount": 18.0,
            "currency": "EUR",
            "status": "succeeded",
            "paid": True,
            "description": "Monthly subscription x2",
            "ts": 0,
        },
    ]
    return {"source": "mock", "payments": mock, "total_paid": 27.0}


def smtp_from() -> str:
    return cfg.get("CORP_SMTP_FROM") or cfg.get("CORP_SMTP_USER") or "corparius@localhost"


def _deliver(to: str, subject: str, body: str, timeout: int) -> str:
    """One real send. Raises on any failure; callers decide what to do with it.
    Returns the Message-ID, which is how a later reply is recognised as a reply.

    Port 465 is implicit TLS and 587 is STARTTLS. Sending STARTTLS at 465 fails
    with an error no operator can read, and 465 is what most providers put in
    their own documentation, so pick the transport from the port.
    """
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = smtp_from()
    msg["To"] = to
    msg["Message-ID"] = make_msgid(domain=smtp_from().rpartition("@")[2] or None)
    msg.set_content(body or "")
    host = cfg.get("CORP_SMTP_HOST", "")
    port = cfg.get_int("CORP_SMTP_PORT", 587)
    user = cfg.get("CORP_SMTP_USER", "")
    password = cfg.get("CORP_SMTP_PASSWORD", "")
    if port == 465:
        with smtplib.SMTP_SSL(host, port, timeout=timeout) as s:
            if user:
                s.login(user, password)
            s.send_message(msg)
        return msg["Message-ID"]
    with smtplib.SMTP(host, port, timeout=timeout) as s:
        if port != 25:
            s.starttls()
        if user:
            s.login(user, password)
        s.send_message(msg)
    return msg["Message-ID"]


def send_email(to: str, subject: str, body: str, timeout: int = 15) -> str | None:
    """Send one email over SMTP, gated by the deliverability guard. Returns None
    when SMTP is not configured (so the caller falls back), else "sent",
    "skipped (reason)" or "error".

    Failures are swallowed on purpose: an agent's turn should survive a bad
    mailbox. Operators pressing Test want the opposite, and get smtp_check().
    """
    status, _message_id = send_email_tracked(to, subject, body, timeout)
    return status


def send_email_tracked(
    to: str, subject: str, body: str, timeout: int = 15
) -> tuple[str | None, str]:
    """send_email, plus the Message-ID of what went out, so the outreach tool can
    recognise the reply later. Kept separate so send_email's contract stays the
    plain None / "sent" / "skipped (...)" / "error" every caller already expects.
    """
    if not cfg.get("CORP_SMTP_HOST", "") or not to:
        return None, ""
    ok, reason = deliverability.can_send(to)
    if not ok:
        return f"skipped ({reason})", ""
    try:
        message_id = _deliver(to, subject, body, timeout)
    except (OSError, smtplib.SMTPException, ValueError):
        return "error", ""
    deliverability.record_send()
    return "sent", message_id or ""


def smtp_diagnosis(exc: Exception, lang="en") -> str:
    """Turn an SMTP failure into something an operator can act on. The stdlib
    messages name the protocol; these name the fix."""
    port = cfg.get_int("CORP_SMTP_PORT", 587)
    host = cfg.get("CORP_SMTP_HOST", "")
    p = lambda en, fr: i18n.pick(lang, en, fr)
    if isinstance(exc, smtplib.SMTPAuthenticationError):
        return p(
            "The server refused these credentials. Most providers need an app-specific "
            "password here, not your account password.",
            "Le serveur a refusé ces identifiants. La plupart des fournisseurs exigent ici "
            "un mot de passe d'application, pas celui de votre compte.",
        )
    if isinstance(exc, smtplib.SMTPNotSupportedError):
        return p(
            f"The server at {host}:{port} did not accept the encryption corparius offered. "
            "Try port 465 (implicit TLS) or 587 (STARTTLS).",
            f"Le serveur {host}:{port} n'a pas accepté le chiffrement proposé. "
            "Essayez le port 465 (TLS implicite) ou 587 (STARTTLS).",
        )
    if isinstance(exc, smtplib.SMTPRecipientsRefused):
        return p(
            "The server accepted the login but refused the recipient address.",
            "Le serveur a accepté la connexion mais refusé l'adresse destinataire.",
        )
    if isinstance(exc, smtplib.SMTPSenderRefused):
        return p(
            f"The server refused '{smtp_from()}' as a sender. It usually has to match "
            "the account you logged in with.",
            f"Le serveur a refusé « {smtp_from()} » comme expéditeur. Il doit en général "
            "correspondre au compte utilisé pour la connexion.",
        )
    if isinstance(exc, socket.gaierror):
        return p(
            f"No such host: '{host}'. Check the server name.",
            f"Hôte introuvable : « {host} ». Vérifiez le nom du serveur.",
        )
    if isinstance(exc, ConnectionRefusedError):
        return p(
            f"{host} refused a connection on port {port}. Check the port.",
            f"{host} a refusé la connexion sur le port {port}. Vérifiez le port.",
        )
    if isinstance(exc, (TimeoutError, socket.timeout)):
        return p(
            f"No answer from {host}:{port} before the timeout. A firewall or the wrong "
            "port would both look like this.",
            f"Aucune réponse de {host}:{port} avant le délai. Un pare-feu ou un mauvais "
            "port donnent tous deux ce résultat.",
        )
    if isinstance(exc, ssl.SSLError):
        return p(
            f"TLS handshake failed on port {port}. Port 465 expects implicit TLS, "
            "587 expects STARTTLS.",
            f"Échec du handshake TLS sur le port {port}. Le 465 attend un TLS implicite, "
            "le 587 attend STARTTLS.",
        )
    return str(exc) or exc.__class__.__name__


def smtp_check(to: str = "", timeout: int = 15, lang="en") -> dict:
    """Actually connect, and actually send if given an address. The console
    calls this so a mail setup can be proved before an agent depends on it."""
    p = lambda en, fr: i18n.pick(lang, en, fr)
    host = cfg.get("CORP_SMTP_HOST", "")
    if not host:
        return {
            "ok": False,
            "configured": False,
            "detail": p(
                "No SMTP server set, so outreach keeps writing to its mock.",
                "Aucun serveur SMTP réglé ; l'outreach continue d'écrire dans son mock.",
            ),
        }
    to = (to or cfg.get("CORP_OUTREACH_TEST_TO", "")).strip()
    port = cfg.get_int("CORP_SMTP_PORT", 587)
    if not to:
        return {
            "ok": False,
            "configured": True,
            "detail": p(
                "Set a fallback recipient (or type an address) to send a test to.",
                "Réglez un destinataire de repli (ou saisissez une adresse) pour envoyer un test.",
            ),
        }
    try:
        _deliver(
            to,
            "corparius test",
            "This is the test message from the corparius console. Your mail setup works.",
            timeout,
        )
    except (OSError, smtplib.SMTPException, ValueError, ssl.SSLError) as exc:
        return {"ok": False, "configured": True, "detail": smtp_diagnosis(exc, lang)}
    return {
        "ok": True,
        "configured": True,
        "detail": p(
            f"Sent to {to} from {smtp_from()} via {host}:{port}. Check the inbox.",
            f"Envoyé à {to} depuis {smtp_from()} via {host}:{port}. Vérifiez la boîte.",
        ),
    }


def stripe_check(timeout: int = 15, lang="en") -> dict:
    """Read the Stripe balance and report what the key actually is. Nothing is
    charged and nothing is created: this only ever reads."""
    p = lambda en, fr: i18n.pick(lang, en, fr)
    key = cfg.get("STRIPE_API_KEY", "").strip()
    if not key:
        return {
            "ok": False,
            "configured": False,
            "detail": p(
                "No Stripe key set, so the payments card shows sample data.",
                "Aucune clé Stripe réglée ; la carte Paiements affiche des données d'exemple.",
            ),
        }
    live = key.startswith(("sk_live", "rk_live"))
    try:
        r = requests.get(
            "https://api.stripe.com/v1/balance",
            headers={"Authorization": f"Bearer {key}"},
            timeout=timeout,
        )
    except requests.RequestException as exc:
        return {
            "ok": False,
            "configured": True,
            "detail": p(f"Could not reach Stripe: {exc}", f"Stripe injoignable : {exc}"),
        }
    if r.status_code == 401:
        return {
            "ok": False,
            "configured": True,
            "detail": p(
                "Stripe rejected this key. Copy it again from the dashboard; a "
                "restricted key with read access to Balance and Charges is enough.",
                "Stripe a rejeté cette clé. Recopiez-la depuis le tableau de bord ; "
                "une clé restreinte en lecture sur Balance et Charges suffit.",
            ),
        }
    if r.status_code == 403:
        return {
            "ok": False,
            "configured": True,
            "detail": p(
                "This key is valid but lacks permission to read the balance. Grant "
                "it read access to Balance and Charges.",
                "Clé valide mais sans droit de lire le solde. Donnez-lui l'accès en "
                "lecture à Balance et Charges.",
            ),
        }
    if not r.ok:
        return {
            "ok": False,
            "configured": True,
            "detail": p(
                f"Stripe answered {r.status_code}: {r.text[:160]}",
                f"Stripe a répondu {r.status_code} : {r.text[:160]}",
            ),
        }
    try:
        avail = (r.json().get("available") or [{}])[0]
        amount = avail.get("amount", 0) / 100
        currency = (avail.get("currency", "") or "").upper()
    except (ValueError, IndexError, AttributeError):
        return {
            "ok": False,
            "configured": True,
            "detail": p(
                "Stripe answered in a shape corparius does not know.",
                "Stripe a répondu dans un format que corparius ne connaît pas.",
            ),
        }
    mode = "live" if live else "test"
    return {
        "ok": True,
        "configured": True,
        "live": live,
        "detail": p(
            f"Connected in {mode} mode. Balance available: {amount:.2f} {currency}.",
            f"Connecté en mode {mode}. Solde disponible : {amount:.2f} {currency}.",
        ),
    }


def send_outreach_email(company: dict, draft: str) -> str | None:
    """Fallback path: send the opener to a single test/notification address
    (CORP_OUTREACH_TEST_TO). Used when no real leads are available."""
    to = cfg.get("CORP_OUTREACH_TEST_TO", "")
    if not to:
        return None
    res = send_email(to, f"{company.get('name', 'corparius')} outreach", draft)
    if res is None:
        return None
    if res == "sent":
        return f"Outreach email sent to {to} via SMTP (live)"
    return f"Outreach {res} for {to}"
