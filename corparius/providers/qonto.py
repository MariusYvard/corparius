"""Qonto, as a second way to be paid. Rank 3, and read-only.

Stripe is a checkout link: a stranger clicks and pays. Qonto is a business account: an operator
issues an invoice and a client transfers. Both are "this company can take money", which is why
`readiness` learns about this one too, and they answer different halves of a French business.

## The division of labour with Stripe

Both are configured at once when an operator wants both, and they are not interchangeable. **Stripe
is the self-serve path**: a stranger reads the sales page, clicks, and pays by card. **Qonto is the
invoiced path**: a named client agreed a price and transfers against an invoice. That is most
business-to-business selling in France, and it is why a company can be entirely ready to be paid
with no checkout link anywhere.

The split decides where each one is used, and the rule is what the money actually does:

  * the sales page carries a Stripe link, because a page is read by strangers;
  * the ads role needs a checkout, because sending a stranger to a page they cannot buy from is
    spending money to produce a bounce;
  * the finance role reads both, because reconciling means asking what landed, and money lands in
    a Stripe balance or a bank account depending on which half of the business it came from.

## What this module does and does not claim

It reads. `check` proves the credentials and `reconcile` reports what came in; nothing here creates
an invoice, moves money, or writes anything to the account. That is deliberate rather than a first
cut: `send_financial_transaction` already sits at the human gate for Stripe, and adding a second
provider that can move money is a decision to take on its own, with its own approval path, rather
than inside a settings change.

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

# How far back a reconcile looks, and how many rows it will read. Both are ceilings rather than
# preferences: this runs unattended twice a day, and an account with four years of history would
# otherwise page through all of it to answer "what came in recently".
WINDOW_DAYS = 30
MAX_ROWS = 100


def credentials() -> tuple[str, str]:
    """(login, secret). Both empty when the operator has not connected an account."""
    return (
        cfg.get("QONTO_LOGIN", "").strip(),
        cfg.get("QONTO_SECRET_KEY", "").strip(),
    )


def configured() -> bool:
    login, secret = credentials()
    return bool(login and secret)


def _get(path: str, params: dict, timeout: int, p) -> tuple[dict, dict | None]:
    """One read of the Qonto API. Returns (body, failure), and exactly one of them is meaningful.

    Extracted when `reconcile` arrived rather than copied, because the interesting part of talking to
    a bank is the four ways it says no (unreachable, wrong credentials, some other status, not JSON)
    and two hand-kept copies of that would drift the moment one of them learned something. The
    failure it returns is already the caller's return shape, `{ok, configured, detail}`, so a caller
    is one `if` away from being correct rather than one translation away.
    """
    login, secret = credentials()
    try:
        answer = requests.get(
            f"{API_BASE}/{path}",
            headers={"Authorization": f"{login}:{secret}"},
            # `None` rather than `{}`, which is requests' own default: a read with no query sends no
            # query string, exactly as it did before this helper existed.
            params=params or None,
            timeout=timeout,
        )
    except requests.RequestException as exc:
        return {}, {
            "ok": False,
            "configured": True,
            "detail": p(f"Could not reach Qonto: {exc}", f"Qonto injoignable : {exc}"),
        }
    if answer.status_code in (401, 403):
        return {}, {
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
        return {}, {
            "ok": False,
            "configured": True,
            "detail": p(
                f"Qonto answered {answer.status_code}.",
                f"Qonto a répondu {answer.status_code}.",
            ),
        }
    try:
        return answer.json() or {}, None
    except ValueError:
        return {}, {
            "ok": False,
            "configured": True,
            "detail": p(
                "Qonto answered something that is not JSON.",
                "Qonto a répondu autre chose que du JSON.",
            ),
        }


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
    body, failure = _get("organization", {}, timeout, p)
    if failure is not None:
        return failure
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


def _euros(amount) -> float:
    """Qonto reports money as a number plus a currency, not as cents. Anything unparseable is zero
    rather than an exception: a reconcile that raises on one odd row tells the operator nothing about
    the other ninety-nine."""
    try:
        return round(float(amount), 2)
    except (TypeError, ValueError):
        return 0.0


def reconcile(timeout: int = 15, lang: str = "en", days: int = WINDOW_DAYS) -> dict:
    """What came in, over a window. Read-only, like everything else here.

    The counterpart to `reconcile_stripe`, and the reason the finance role is worth running for a
    company that never had a checkout link. Stripe answers "what did strangers pay"; this answers
    "what landed in the account", which for an invoiced business is the whole of the revenue.

    Two calls, both bounded. The organization gives the accounts and the balance the bank itself
    reports, then one page of settled credits gives what arrived. `MAX_ROWS` is a ceiling rather
    than a preference: this runs unattended twice a day, and an account with years of history would
    otherwise page through all of it to answer a question about last month.

    **It does not attribute payments to customers.** A transfer carries a label the payer typed, and
    matching those to invoices is guesswork that would be reported as fact. The labels are handed
    back for a person or a model to read; the arithmetic stops at the total.
    """
    from datetime import datetime, timedelta, timezone

    def p(en: str, fr: str) -> str:
        return i18n.pick(lang, en, fr)

    if not configured():
        return {
            "ok": False,
            "configured": False,
            "detail": p("No Qonto account connected.", "Aucun compte Qonto connecté."),
        }

    body, failure = _get("organization", {}, timeout, p)
    if failure is not None:
        return failure
    accounts = ((body or {}).get("organization") or {}).get("bank_accounts") or []
    if not accounts:
        return {
            "ok": False,
            "configured": True,
            "detail": p(
                "These credentials reach an organization with no bank account.",
                "Ces identifiants atteignent une organisation sans compte bancaire.",
            ),
        }

    balance = sum(_euros(a.get("balance")) for a in accounts if isinstance(a, dict))
    since = datetime.now(timezone.utc) - timedelta(days=max(1, days))
    rows: list[dict] = []
    for account in accounts:
        if not isinstance(account, dict) or not account.get("id"):
            continue
        page, failure = _get(
            "transactions",
            {
                "bank_account_id": account["id"],
                "settled_at_from": since.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
                "side": "credit",
                "per_page": MAX_ROWS,
            },
            timeout,
            p,
        )
        if failure is not None:
            return failure
        rows.extend(t for t in (page.get("transactions") or []) if isinstance(t, dict))

    # Settled only. A transaction Qonto is still processing is not money the company has, and
    # counting it would make a reconcile optimistic in exactly the month it matters.
    settled = [t for t in rows if str(t.get("status") or "").lower() in ("completed", "settled")]
    came_in = round(sum(_euros(t.get("amount")) for t in settled), 2)
    labels = [str(t.get("label") or "").strip() for t in settled]
    labels = [label for label in labels if label][:8]

    detail = p(
        f"Qonto: {came_in} EUR in over {days} days, {len(settled)} transfer(s); "
        f"balance {round(balance, 2)} EUR.",
        f"Qonto : {came_in} EUR encaissés sur {days} jours, {len(settled)} virement(s) ; "
        f"solde {round(balance, 2)} EUR.",
    )
    if labels:
        detail += p(" From: ", " De : ") + ", ".join(labels)
    return {
        "ok": True,
        "configured": True,
        "balance_eur": round(balance, 2),
        "received_eur": came_in,
        "transfers": len(settled),
        "days": days,
        "labels": labels,
        "detail": detail,
    }
