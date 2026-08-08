"""Creating a company. Rank 5.

**The gap `tests/test_two_callers_agree.py` named.** `cli.cmd_init` looks like the command-line
half of the console's wizard and is not — it stamps the state of a company that already exists.
So there was no way to create one from a terminal at all: an operator wrote
`companies/<slug>/company.yaml` by hand, which means guessing the shape, the field names, and
which of them are required.

That mattered more than a missing convenience. The wizard's whole design note is that it "asks
for two fields and fills the rest from the same validator the editor uses, so a company created
here and one edited later can never disagree about what a company is". A hand-written file has
none of that: `company.validate` repairs what it can and *names* the rest, and nobody was
running it at creation time.

Two fields, then. A name, and a product — everything else has a default, and a template fills
the examples. What is refused is refused with the same words the console shows, because it is
the same validator.
"""

from __future__ import annotations

from .. import company as company_mod
from .errors import Refused

DEFAULT_SESSION_TOKENS = 80_000


def create(
    store,
    *,
    name: str,
    one_liner: str = "",
    product: str = "",
    segment: str = "",
    template: str = "",
    agents: dict | None = None,
    session_tokens: int = DEFAULT_SESSION_TOKENS,
    lang: str = "en",
) -> dict:
    """Write a new company and stamp its state. Returns the slug, the config and any warnings.

    `template` prefills offer, ICP and which agents are on; **explicit arguments still win**, so
    a typed name and product override the template's examples rather than the other way round.
    That order is the whole reason a template is safe to offer.

    `warnings` is not an error list. `company.validate` repairs what it can and says so — a
    negative ad budget becomes zero and the operator is told — and refusing the creation over a
    repairable field would be the wrong trade for someone starting out.
    """
    tpl = company_mod.template(str(template or "")) or {}
    lang = "fr" if str(lang or "").startswith("fr") else "en"
    offer: dict = {"product": product or tpl.get(f"product_{lang}", "")}
    if tpl:
        offer["price_eur"] = tpl.get("price_eur")
        offer["billing"] = tpl.get("billing", "stripe")
    icp: dict = {"segment": segment or tpl.get(f"segment_{lang}", "")}
    if tpl:
        icp["channels"] = tpl.get("channels", [])
        icp["pains"] = tpl.get(f"pains_{lang}", [])
    cfg, errors, warnings = company_mod.validate(
        {
            "name": name or "",
            "one_liner": one_liner or "",
            "offer": offer,
            "icp": icp,
            "agents": {**tpl.get("agents", {}), **dict(agents or {})},
            "budgets": {"session_tokens": session_tokens},
        }
    )
    if errors:
        raise Refused("; ".join(errors))
    path = company_mod.path_for(cfg["slug"])
    if path.exists():
        raise Refused(f"company '{cfg['slug']}' already exists")
    company_mod.dump(cfg, path)
    # The state row `init` would otherwise have to be run for. A company created and not
    # stamped looks to the loop like one that has already played its first tick.
    store.save_state(cfg["slug"], {"tick": 0})
    return {"slug": cfg["slug"], "config": cfg, "warnings": warnings}


def templates(lang: str = "en") -> list[dict]:
    """The starter templates, as a caller would show them.

    Here rather than read from `company.TEMPLATES` twice: the console renders these in the
    wizard and a terminal lists them for `--template`, and two readings of one table is how they
    come to offer different sets.
    """
    code = "fr" if str(lang or "").startswith("fr") else "en"
    return [
        {
            "id": tpl["id"],
            "label": tpl.get(f"label_{code}") or tpl.get("label_en", tpl["id"]),
            "product": tpl.get(f"product_{code}", ""),
            "agents": sorted(k for k, v in (tpl.get("agents") or {}).items() if v),
        }
        for tpl in company_mod.TEMPLATES
    ]


def delete(store, slug: str, confirm: str, purge: bool = False) -> dict:
    """Move a company's config to `companies/.trash/`, and optionally purge its store rows.

    **Nothing is destroyed by the trash half**, which is the whole reason this is safe to offer
    from a terminal: the config is moved, so a mistake is a `mv` away from undone. `purge` is
    the half that cannot be undone, and it is a separate argument for that reason.

    `confirm` has to equal the slug. Typing a name is the cheapest possible proof that the
    operator meant this company and not the one above it in a list — and the same guard the
    console's dialog uses, because a destructive action reachable two ways must not be easier
    one of them.

    The traversal guard comes first and is not incidental: `slug not in list_slugs()` means only
    a name the glob actually produced is ever turned into a path.
    """
    if slug not in company_mod.list_slugs():
        raise Refused(f"unknown company '{slug}'")
    if confirm != slug:
        raise Refused("type the company slug to confirm")
    try:
        dest = company_mod.trash(slug)
    except FileNotFoundError as exc:
        raise Refused(f"unknown company '{slug}'") from exc
    removed = store.purge_company(slug) if purge else {}
    return {
        "slug": slug,
        "trashed": str(dest),
        "purged": bool(purge),
        # Per table, because "everything" was the claim that turned out to cover six of
        # thirteen. An operator reading a count can tell what actually went.
        "removed": {table: n for table, n in removed.items() if n},
    }
