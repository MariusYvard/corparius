"""What a company actually has yet. Rank 4, and the one place that decides.

Four facts, each a boolean, each read from something the operator did rather than from something
they declared: an offer in the company file, a published address on disk, a mail account in the
settings, a way to be paid. Nothing here asks a model, and nothing here is a preference.

## Why this exists rather than living in two places

`api/adapters.golive_status` computed three of these for the console's *Go live* card, and the
scheduler computed none of them — so the product could tell an operator "you cannot take money yet"
on one screen while the ads agent spent a turn adjusting bids on the next. One fact, two answers, is
the shape of defect this codebase keeps paying for: it is the same reasoning that collapsed the
document retrieval into a single selection after `inventory` and `context` disagreed for one commit.

So the fact is computed here, at a rank both callers can reach, and `golive_status` became a
presentation of it.

## Why these four and not a "stage"

A stage number is a vocabulary an operator has to learn, and it forces an order that is not real —
plenty of companies wire a payment link before they have a public page. These four are independent,
they are already the three things the *Go live* card names (plus the offer, which the wizard asks
for first), and a role declares which ones it needs. `roster.AgentSpec.needs` is that declaration,
and it reads as a sentence: outreach needs a site, finance needs payment.

## What is deliberately not a fact here

**"Has a customer."** It would be the truest signal for support and finance, and it cannot be had:
a company with a payment link and no charges is indistinguishable from one whose provider is not
configured, and guessing between them would gate a role on the absence of a webhook nobody set up.
Payment wired is the honest proxy — it says the operator has decided to sell, which is what the
roles below it need in order to be worth a turn.
"""

from __future__ import annotations

from pathlib import Path

from .config import cfg
from .kernel import paths

# The closed set. `roster` validates its `needs` against this, and
# `tests/test_readiness.py` fails on a fact nothing declares and on a need no fact answers — the
# both-ends rule this project applies to every registry.
FACTS = ("offer", "site", "mail", "payment", "checkout")


def invoiced() -> bool:
    """A business paid by transfer against an invoice, rather than by a checkout a stranger clicks.

    Public and separate from `facts` because two places need it and it must not be spelled twice:
    the gate here, and the sales page, which says how a visitor pays. A second copy of "both Qonto
    keys are set" in `sitegen` would be the kind of duplicated predicate that goes out of step the
    first time the condition changes, and it would drag `requests` into the site builder to boot.

    Reads the settings rather than the provider module on purpose. The question is what the operator
    configured, not whether Qonto answered: a bank having an outage does not stop a company being
    the kind of company that invoices.
    """
    return bool(cfg.get("QONTO_LOGIN", "").strip() and cfg.get("QONTO_SECRET_KEY", "").strip())


def _offer(company: dict) -> bool:
    """Something to sell, said in the company's own file.

    A name alone is not it: the wizard writes `offer.name` from the company name before the operator
    has decided anything, so requiring a name would make this true on an empty company. A price or a
    description is the operator having answered the question.
    """
    offer = (company or {}).get("offer") or {}
    if not isinstance(offer, dict):
        return False
    # Both spellings, because the company file has carried both: the example ships `price_eur` and
    # `product`, the wizard writes `price` and `description`. Reading one of the pair is how a
    # company that *has* an offer gets told it has none — measured on `companies/example`, which
    # would have failed this on `price` alone.
    priced = any(str(offer.get(k) or "").strip() not in ("", "0") for k in ("price", "price_eur"))
    said = " ".join(
        str(offer.get(k) or "") for k in ("description", "pitch", "product", "includes")
    )
    return priced or len(said.strip()) > 20


def published_url(data_path: str, slug: str) -> str:
    """The public address a deploy reported, or "" if the site was never published.

    The marker holds the provider's own answer — `netlify:https://…` or `local:/var/www/…` — so a
    URL exists only for the providers that serve one. A local copy is a published *site* and not a
    published *address*, which is why the two are separated below rather than merged.
    """
    marker = Path(paths.site_dir(data_path, slug)) / ".published"
    if not marker.is_file():
        return ""
    try:
        target = marker.read_text(encoding="utf-8").strip()
    except OSError:
        return ""
    _, _, rest = target.partition(":")
    return rest.strip() if rest.strip().startswith("http") else ""


def facts(company: dict, data_path: str, slug: str = "") -> dict[str, bool]:
    """The four, for one company. Cheap enough to call every tick: one file test and three lookups.

    `slug` falls back to the company's own, so a caller that already holds the dict does not have to
    pass the same thing twice.
    """
    slug = slug or str((company or {}).get("slug") or "")
    offer = (company or {}).get("offer") or {}
    link = str((offer.get("payment_link") if isinstance(offer, dict) else "") or "").strip()
    if not link:
        link = cfg.get("CORP_STRIPE_PAYMENT_LINK", "").strip()
    marker = Path(paths.site_dir(data_path, slug)) / ".published" if slug else None
    site = (company or {}).get("site") or {}
    # A site the operator runs outside corparius is a public address like any other, and the roles
    # that wait for one have no business asking who deployed it. Without this the gate held outreach
    # forever on exactly the companies most ready to use it: the ones that already had a site.
    external = bool(isinstance(site, dict) and site.get("external") and site.get("url"))
    checkout = link.startswith("http") or bool(cfg.get("STRIPE_API_KEY", "").strip())
    return {
        "offer": _offer(company),
        # Published, not merely built. A site in the data folder is a draft; the marker is written
        # by `app/publish.py` only after a provider accepted it, which is what makes a link worth
        # sending to a stranger.
        "site": external or bool(marker and marker.is_file()),
        "mail": bool(
            cfg.get("CORP_SMTP_HOST", "").strip() and cfg.get("CORP_SMTP_USER", "").strip()
        ),
        # A link the operator pasted, a Stripe key, or a Qonto account. Each is the operator saying
        # "this company sells", and none proves a charge has ever landed; the module docstring says
        # why no stronger signal is available honestly.
        #
        # Qonto counts because a French company selling to other businesses is paid by transfer
        # against an invoice, not by a checkout link, and a gate that only knew about checkout
        # would hold its finance agent forever on exactly that company.
        "payment": checkout or invoiced(),
        # **And the two are not interchangeable, which is why there are two facts.**
        #
        # `payment` answers "can this company be paid at all", which is what finance needs: it has
        # one reconciler per route and runs whichever applies. `checkout` answers the narrower
        # question "can a stranger buy without talking to anybody", which is what paid traffic
        # needs. Sending someone who clicked an ad to a page whose only call to action is "contact
        # us" is spending money to produce a conversation, and an ads agent gated on `payment`
        # would do exactly that for every invoiced business.
        "checkout": checkout,
    }
