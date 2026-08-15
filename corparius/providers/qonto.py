"""Qonto, as a second way to be paid. Rank 3, and read-only.

Stripe is a checkout link: a stranger clicks and pays. Qonto is a business account: an operator
issues an invoice and a client transfers. Both are "this company can take money", which is why
`readiness` learns about this one too, and they answer different halves of a French business.

## What this module does and does not claim

It reads. `check` fetches the organization and reports whether the credentials work; nothing here
creates an invoice, moves money, or writes anything to the account. That is deliberate for a first
version: `send_financial_transaction` already sits at the human gate for Stripe, and adding a second
provider that can move money is a decision to take on its own rather than inside a settings change.

**On the French e-invoicing mandate.** From 2026 every business must be able to *receive* electronic
invoices and large ones must issue them, with the obligation reaching everybody in 2027, and the
transmission goes through an approved platform. Whether a given bank is such a platform is a fact
about a public register, not about this code, and corparius does not assert it: what the mandate
requires of an operator is in `docs/conformite-fr.md`, and the fields an invoice must carry are the
`legal:` block a company already declares. This module holds credentials and proves they work.

## Not in `integrations.py`

That module holds 213 statements of SMTP, IMAP and Stripe protocol that no test exercises, and the
restructuring plan names it as untouchable for exactly that reason. A new provider goes in a new
file, where its own tests can reach it.
"""

from __future__ import annotations

import requests

from ..config import cfg
from ..kernel import i18n

# Qonto's own base. Kept here rather than inlined so a test can point it somewhere else, and so an
# operator on a different region is one setting away rather than one fork away.
API_BASE = "https://thirdparty.qonto.com/v2"


def credentials() -> tuple[str, str]:
    """(login, secret). Both empty when the operator has not connected an account."""
    return (
        cfg.get("QONTO_LOGIN", "").strip(),
        cfg.get("QONTO_SECRET_KEY", "").strip(),
    )


def configured() -> bool:
    login, secret = credentials()
    return bool(login and secret)


def check(timeout: int = 15, lang: str = "en") -> dict:
    """Prove the credentials, by reading. Nothing is created and no money moves.

    The same shape `stripe_check` returns, because the console renders both through one card and a
    second shape would be a second card nobody asked for: `{ok, configured, detail}` plus whatever
    the caller can use.
    """

    def p(en: str, fr: str) -> str:
        return i18n.pick(lang, en, fr)

    login, secret = credentials()
    if not (login and secret):
        return {
            "ok": False,
            "configured": False,
            "detail": p(
                "No Qonto credentials set. They are in the Qonto app under Settings, "
                "Integrations, API keys: a login and a secret key.",
                "Aucun identifiant Qonto. Ils sont dans l'app Qonto sous Paramètres, "
                "Intégrations, clés API : un login et une clé secrète.",
            ),
        }
    try:
        answer = requests.get(
            f"{API_BASE}/organization",
            headers={"Authorization": f"{login}:{secret}"},
            timeout=timeout,
        )
    except requests.RequestException as exc:
        return {
            "ok": False,
            "configured": True,
            "detail": p(f"Could not reach Qonto: {exc}", f"Qonto injoignable : {exc}"),
        }
    if answer.status_code in (401, 403):
        return {
            "ok": False,
            "configured": True,
            "detail": p(
                "Qonto rejected these credentials. Copy the login and the secret key again "
                "from the Qonto app; read access to the organization is enough.",
                "Qonto a rejeté ces identifiants. Recopiez le login et la clé secrète depuis "
                "l'app Qonto ; un accès en lecture à l'organisation suffit.",
            ),
        }
    if answer.status_code >= 400:
        return {
            "ok": False,
            "configured": True,
            "detail": p(
                f"Qonto answered {answer.status_code}.",
                f"Qonto a répondu {answer.status_code}.",
            ),
        }
    try:
        body = answer.json()
    except ValueError:
        return {
            "ok": False,
            "configured": True,
            "detail": p(
                "Qonto answered something that is not JSON.",
                "Qonto a répondu autre chose que du JSON.",
            ),
        }
    org = (body or {}).get("organization") or {}
    accounts = org.get("bank_accounts") or []
    # The slug is what an operator recognises, and the count is what tells them the key reaches the
    # account they meant rather than an empty organization.
    return {
        "ok": True,
        "configured": True,
        "organization": str(org.get("slug") or ""),
        "accounts": len(accounts),
        "detail": p(
            f"Connected to {org.get('slug') or 'Qonto'}, {len(accounts)} account(s).",
            f"Connecté à {org.get('slug') or 'Qonto'}, {len(accounts)} compte(s).",
        ),
    }
