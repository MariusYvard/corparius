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

ROOT = Path(__file__).resolve().parent.parent

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
    with open(path, "r", encoding="utf-8") as fh:
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
