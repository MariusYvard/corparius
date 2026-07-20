"""The company config: one loader, one validator, one writer.

Until now three modules parsed company.yaml with a bare yaml.safe_load and their
own defaults (cli, webui, mcp_server), so an empty file raised AttributeError
from inside setdefault and a typo'd agent key silently enabled a role. Every
consumer then defended itself with .get() chains. This module is the single
place that decides what a company is.

validate() never raises and never rejects a whole file for one bad field: an
operator editing from the console should get their config back with the bad part
named, not an error page. Errors say what was refused; warnings say what was
repaired.
"""
from __future__ import annotations
import os
import re
import time
from pathlib import Path

import yaml

from . import paths

# The writable home under which `companies/` lives. In a source checkout this is
# the repository root (unchanged); frozen, it is a per-OS directory that
# seed_examples() populates from the bundled example on first run. Kept as a
# module attribute so the tests can monkeypatch it.
ROOT = paths.user_home()

SLUG_RE = re.compile(r"[^a-z0-9]+")

ROLES = ("ceo", "social", "outreach", "support", "ads",
         "finance", "strategy", "competitor", "design", "coder")

DEFAULT_AGENTS = {"ceo": True, "social": True, "outreach": True, "support": True,
                  "ads": False, "finance": True, "strategy": True,
                  "competitor": True, "design": True, "coder": False}

# Channels the social agent can schedule to. Kept small on purpose: an unknown
# channel is a typo, not a feature.
CHANNELS = ("linkedin", "x", "reddit", "mastodon", "bluesky", "youtube", "instagram")

BILLING = ("stripe", "manual", "none")

TOKENS_MIN, TOKENS_MAX = 1000, 5_000_000

DEFAULT_HITL = ["send_financial_transaction", "publish_production_code", "deploy_site"]


# Starter templates. The blank page at creation is real friction: a newcomer
# knows their business but not what to put for ICP, channels or which agents.
# A template fills a sensible starting point they then edit. The text fields are
# examples per language; agents/channels/billing are the structural choices.
TEMPLATES: list[dict] = [
    {"id": "saas", "label_en": "SaaS / web app", "label_fr": "SaaS / app web",
     "product_en": "A self-serve web app on a monthly subscription.",
     "product_fr": "Une app web en libre-service, sur abonnement mensuel.",
     "segment_en": "Small teams who feel this pain and have a budget to fix it",
     "segment_fr": "Petites équipes qui vivent ce problème et ont un budget pour le régler",
     "pains_en": ["Doing it by hand eats hours every week", "Existing tools are bloated and costly"],
     "pains_fr": ["Le faire à la main coûte des heures chaque semaine", "Les outils existants sont lourds et chers"],
     "channels": ["linkedin", "x"], "price_eur": 29, "billing": "stripe",
     "agents": {"ads": False, "coder": True}},
    {"id": "ecom", "label_en": "Online shop", "label_fr": "Boutique en ligne",
     "product_en": "A physical product sold online, one-off purchases.",
     "product_fr": "Un produit physique vendu en ligne, à l'unité.",
     "segment_en": "Shoppers who value this over the mass-market option",
     "segment_fr": "Acheteurs qui préfèrent ceci à l'option grand public",
     "pains_en": ["Mass-produced versions feel generic", "Slow or unreliable delivery elsewhere"],
     "pains_fr": ["Les versions industrielles font génériques", "Livraison lente ou peu fiable ailleurs"],
     "channels": ["instagram", "x"], "price_eur": 45, "billing": "stripe",
     "agents": {"ads": True, "coder": False}},
    {"id": "agency", "label_en": "Agency / services", "label_fr": "Agence / services",
     "product_en": "A done-for-you service billed per project or retainer.",
     "product_fr": "Un service clé en main, facturé au projet ou au forfait.",
     "segment_en": "Businesses that need this done but won't hire in-house",
     "segment_fr": "Entreprises qui en ont besoin sans vouloir recruter en interne",
     "pains_en": ["No in-house expertise for this", "Past vendors over-promised and under-delivered"],
     "pains_fr": ["Pas d'expertise en interne", "Prestataires passés qui promettent trop"],
     "channels": ["linkedin"], "price_eur": None, "billing": "manual",
     "agents": {"ads": False, "coder": False}},
    {"id": "newsletter", "label_en": "Newsletter / media", "label_fr": "Newsletter / média",
     "product_en": "A paid newsletter or content membership.",
     "product_fr": "Une newsletter payante ou un abonnement à du contenu.",
     "segment_en": "People who want to stay ahead on this topic",
     "segment_fr": "Des gens qui veulent garder une longueur d'avance sur ce sujet",
     "pains_en": ["Too much noise, too little signal elsewhere", "No time to follow it all"],
     "pains_fr": ["Trop de bruit, trop peu de signal ailleurs", "Pas le temps de tout suivre"],
     "channels": ["linkedin", "x", "bluesky"], "price_eur": 9, "billing": "stripe",
     "agents": {"ads": False, "coder": False}},
]


def template(tid: str) -> dict | None:
    return next((dict(t) for t in TEMPLATES if t["id"] == tid), None)


def slugify(name: str) -> str:
    return SLUG_RE.sub("-", name.strip().lower()).strip("-")


def path_for(slug: str) -> Path:
    return ROOT / "companies" / slug / "company.yaml"


def list_slugs(root: Path | None = None) -> list[str]:
    base = (root or ROOT) / "companies"
    if not base.is_dir():
        return []
    return sorted(p.parent.name for p in base.glob("*/company.yaml")
                  if not p.parent.name.startswith("."))


def load(path, slug: str | None = None) -> dict:
    """Read and normalise. Raises FileNotFoundError or ValueError; callers that
    want softer handling use validate() on the result."""
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(str(path))
    with open(path, encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)
    if raw is None:
        raw = {}                       # an empty file is an empty company, not a crash
    if not isinstance(raw, dict):
        raise ValueError(f"{path}: expected a mapping, found {type(raw).__name__}")
    raw.setdefault("slug", slug or path.parent.name)
    cfg, _errors, _warnings = validate(raw)
    return cfg


def _int(value, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def validate(raw: dict) -> tuple[dict, list[str], list[str]]:
    """Normalise a company dict. Returns (cfg, errors, warnings)."""
    errors: list[str] = []
    warnings: list[str] = []
    raw = dict(raw or {})

    name = str(raw.get("name", "")).strip()
    if not name:
        errors.append("name is required")
    slug = slugify(str(raw.get("slug", "")) or name)
    if not slug:
        errors.append("slug is empty; give the company a name with letters or digits")

    offer_in = raw.get("offer") or {}
    if not isinstance(offer_in, dict):
        warnings.append("offer was not a mapping; reset to defaults")
        offer_in = {}
    product = str(offer_in.get("product", "")).strip()
    if not product:
        errors.append("offer.product is required")

    price = offer_in.get("price_eur")
    if price in (None, ""):
        price = None                   # None is meaningful: the site reads "Let's talk"
    else:
        try:
            price = float(price)
            price = int(price) if float(price).is_integer() else price
            if price < 0:
                errors.append("offer.price_eur cannot be negative")
        except (TypeError, ValueError):
            errors.append(f"offer.price_eur: expected a number, got {offer_in['price_eur']!r}")
            price = None

    billing = str(offer_in.get("billing", "stripe")).strip().lower() or "stripe"
    if billing not in BILLING:
        warnings.append(f"offer.billing '{billing}' is not one of {', '.join(BILLING)}; kept as free text")

    icp_in = raw.get("icp") or {}
    if not isinstance(icp_in, dict):
        warnings.append("icp was not a mapping; reset to defaults")
        icp_in = {}
    channels = [str(c).strip().lower() for c in (icp_in.get("channels") or []) if str(c).strip()]
    unknown = [c for c in channels if c not in CHANNELS]
    if unknown:
        warnings.append(f"icp.channels: dropped unknown {', '.join(unknown)} "
                        f"(known: {', '.join(CHANNELS)})")
        channels = [c for c in channels if c in CHANNELS]
    if not channels:
        channels = ["linkedin"]
    pains = [str(p).strip() for p in (icp_in.get("pains") or []) if str(p).strip()]

    agents_in = raw.get("agents") or {}
    if not isinstance(agents_in, dict):
        warnings.append("agents was not a mapping; reset to defaults")
        agents_in = {}
    stray = [k for k in agents_in if k not in ROLES]
    if stray:
        warnings.append(f"agents: dropped unknown role(s) {', '.join(stray)}")
    agents = {role: bool(agents_in.get(role, DEFAULT_AGENTS[role])) for role in ROLES}

    budgets_in = raw.get("budgets") or {}
    if not isinstance(budgets_in, dict):
        warnings.append("budgets was not a mapping; reset to defaults")
        budgets_in = {}
    session = _int(budgets_in.get("session_tokens", 80000), 80000)
    clamped = max(TOKENS_MIN, min(session, TOKENS_MAX))
    if clamped != session:
        warnings.append(f"budgets.session_tokens clamped to {clamped}")
    session = clamped
    tpm = _int(budgets_in.get("tokens_per_minute", max(1000, session // 10)),
               max(1000, session // 10))
    tpm = max(100, min(tpm, session))
    ads_eur = _int(budgets_in.get("daily_ad_spend_eur", 0), 0)
    if ads_eur < 0:
        warnings.append("budgets.daily_ad_spend_eur cannot be negative; set to 0")
        ads_eur = 0
    if ads_eur and not agents["ads"]:
        warnings.append("budgets.daily_ad_spend_eur is set but the ads agent is off")

    from .tools import TOOLS       # local import: tools imports config, config imports cfg
    hitl_in = raw.get("hitl_tools")
    hitl = [str(x).strip() for x in (hitl_in if isinstance(hitl_in, list) else DEFAULT_HITL)
            if str(x).strip()]
    unknown_tools = [x for x in hitl if x not in TOOLS]
    if unknown_tools:
        warnings.append(f"hitl_tools: {', '.join(unknown_tools)} match no tool and gate nothing")

    cfg = {
        "slug": slug,
        "name": name,
        "one_liner": str(raw.get("one_liner", "")).strip() or product,
        "offer": {"product": product, "price_eur": price, "billing": billing,
                  "payment_link": str(offer_in.get("payment_link", "")).strip()},
        "icp": {"segment": str(icp_in.get("segment", "")).strip() or "To be defined",
                "channels": channels, "pains": pains},
        "agents": agents,
        "budgets": {"session_tokens": session, "tokens_per_minute": tpm,
                    "daily_ad_spend_eur": ads_eur},
        "hitl_tools": hitl,
    }
    return cfg, errors, warnings


def dump(cfg: dict, path) -> Path:
    """Write atomically: a half-written company.yaml would break every loader,
    including the one that would let the operator fix it."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        yaml.safe_dump(cfg, fh, sort_keys=False, allow_unicode=True)
    os.replace(tmp, path)
    return path


def trash(slug: str, root: Path | None = None) -> Path:
    """Move a company aside instead of deleting it. The operator's config is not
    ours to destroy, and a mistyped slug should be recoverable."""
    base = (root or ROOT) / "companies"
    src = base / slug
    if not (src / "company.yaml").is_file():
        raise FileNotFoundError(slug)
    dest_dir = base / ".trash"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"{slug}-{int(time.time())}"
    os.replace(src, dest)
    return dest


def seed_examples(root: Path | None = None) -> list[str]:
    """Populate a fresh writable companies dir from the bundled example. A no-op
    from a source checkout (the example already lives there) and on every later
    run; it matters only on a first frozen launch, whose companies dir is empty.
    Returns the resulting slug list."""
    import shutil
    base = (root or ROOT) / "companies"
    src = paths.example_company_src()
    dest = base / src.name
    if (dest / "company.yaml").is_file() or not (src / "company.yaml").is_file():
        return list_slugs(root)
    shutil.copytree(src, dest, dirs_exist_ok=True)
    return list_slugs(root)
