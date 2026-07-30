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

from . import paths, permissions

# The writable home under which `companies/` lives. In a source checkout this is
# the repository root (unchanged); frozen, it is a per-OS directory that
# seed_examples() populates from the bundled example on first run. Kept as a
# module attribute so the tests can monkeypatch it.
ROOT = paths.user_home()

SLUG_RE = re.compile(r"[^a-z0-9]+")

ROLES = (
    "ceo",
    "social",
    "outreach",
    "support",
    "ads",
    "finance",
    "strategy",
    "competitor",
    "design",
    "coder",
)

DEFAULT_AGENTS = {
    "ceo": True,
    "social": True,
    "outreach": True,
    "support": True,
    "ads": False,
    "finance": True,
    "strategy": True,
    "competitor": True,
    "design": True,
    "coder": False,
}

# Channels the social agent can schedule to. Kept small on purpose: an unknown
# channel is a typo, not a feature.
CHANNELS = ("linkedin", "x", "reddit", "mastodon", "bluesky", "youtube", "instagram")

BILLING = ("stripe", "manual", "none")

TOKENS_MIN, TOKENS_MAX = 1000, 5_000_000

DEFAULT_HITL = ["send_financial_transaction", "publish_production_code", "deploy_site"]

# The languages this build can write a sales page in. A company may declare any
# language it likes — the field is free text and every agent prompt honours it —
# but the page's own furniture (section headings, the CTA, the billing note) is
# only translated for these, and anything else falls back to English furniture
# around content that is still in the company's language. Better an honest
# mixture than a French heading invented by nobody.
LANGUAGES = ("en", "fr", "es", "de", "it", "pt", "nl")

# Function words that do not travel. Each of these is common in its own language
# and absent or rare in the others, which is all a default needs to be: the field
# is written into company.yaml at creation, so the operator sees the guess and
# can correct it once, rather than the guess running on every load.
_MARKERS = {
    "fr": ("le", "la", "les", "des", "une", "vous", "pour", "avec", "sans", "votre", "qui", "est"),
    "es": ("el", "los", "las", "una", "para", "con", "sin", "que", "sus", "por", "más", "tu"),
    "de": ("der", "die", "das", "und", "für", "mit", "ohne", "ihre", "sie", "ein", "eine", "nicht"),
    "it": ("il", "lo", "gli", "una", "per", "con", "senza", "che", "sono", "tuo", "più", "del"),
    "pt": ("os", "as", "uma", "para", "com", "sem", "que", "seu", "sua", "mais", "não", "você"),
    "nl": ("de", "het", "een", "voor", "met", "zonder", "uw", "jouw", "niet", "van", "zijn", "je"),
    "en": ("the", "a", "an", "for", "with", "without", "your", "you", "that", "of", "is", "to"),
}
_WORD_RE = re.compile(r"[a-zà-öø-ÿ]+")


def detect_language(text: str) -> str:
    """Guess a language from the words the operator wrote. Falls back to `en`.

    Deliberately crude — no dependency, no model call, and the answer is only a
    default that gets written down for review. It exists because a French
    company drafted English support replies for want of anybody ever saying
    which language it speaks.
    """
    words = _WORD_RE.findall(str(text or "").lower())
    if not words:
        return "en"
    counts = {lang: sum(w in marks for w in words) for lang, marks in _MARKERS.items()}
    best = max(counts, key=lambda lang: (counts[lang], lang == "en"))
    return best if counts[best] else "en"


# Starter templates. The blank page at creation is real friction: a newcomer
# knows their business but not what to put for ICP, channels or which agents.
# A template fills a sensible starting point they then edit. The text fields are
# examples per language; agents/channels/billing are the structural choices.
TEMPLATES: list[dict] = [
    {
        "id": "saas",
        "label_en": "SaaS / web app",
        "label_fr": "SaaS / app web",
        "product_en": "A self-serve web app on a monthly subscription.",
        "product_fr": "Une app web en libre-service, sur abonnement mensuel.",
        "segment_en": "Small teams who feel this pain and have a budget to fix it",
        "segment_fr": "Petites équipes qui vivent ce problème et ont un budget pour le régler",
        "pains_en": [
            "Doing it by hand eats hours every week",
            "Existing tools are bloated and costly",
        ],
        "pains_fr": [
            "Le faire à la main coûte des heures chaque semaine",
            "Les outils existants sont lourds et chers",
        ],
        "channels": ["linkedin", "x"],
        "price_eur": 29,
        "billing": "stripe",
        "agents": {"ads": False, "coder": True},
    },
    {
        "id": "ecom",
        "label_en": "Online shop",
        "label_fr": "Boutique en ligne",
        "product_en": "A physical product sold online, one-off purchases.",
        "product_fr": "Un produit physique vendu en ligne, à l'unité.",
        "segment_en": "Shoppers who value this over the mass-market option",
        "segment_fr": "Acheteurs qui préfèrent ceci à l'option grand public",
        "pains_en": [
            "Mass-produced versions feel generic",
            "Slow or unreliable delivery elsewhere",
        ],
        "pains_fr": [
            "Les versions industrielles font génériques",
            "Livraison lente ou peu fiable ailleurs",
        ],
        "channels": ["instagram", "x"],
        "price_eur": 45,
        "billing": "stripe",
        "agents": {"ads": True, "coder": False},
    },
    {
        "id": "agency",
        "label_en": "Agency / services",
        "label_fr": "Agence / services",
        "product_en": "A done-for-you service billed per project or retainer.",
        "product_fr": "Un service clé en main, facturé au projet ou au forfait.",
        "segment_en": "Businesses that need this done but won't hire in-house",
        "segment_fr": "Entreprises qui en ont besoin sans vouloir recruter en interne",
        "pains_en": [
            "No in-house expertise for this",
            "Past vendors over-promised and under-delivered",
        ],
        "pains_fr": ["Pas d'expertise en interne", "Prestataires passés qui promettent trop"],
        "channels": ["linkedin"],
        "price_eur": None,
        "billing": "manual",
        "agents": {"ads": False, "coder": False},
    },
    {
        "id": "newsletter",
        "label_en": "Newsletter / media",
        "label_fr": "Newsletter / média",
        "product_en": "A paid newsletter or content membership.",
        "product_fr": "Une newsletter payante ou un abonnement à du contenu.",
        "segment_en": "People who want to stay ahead on this topic",
        "segment_fr": "Des gens qui veulent garder une longueur d'avance sur ce sujet",
        "pains_en": ["Too much noise, too little signal elsewhere", "No time to follow it all"],
        "pains_fr": ["Trop de bruit, trop peu de signal ailleurs", "Pas le temps de tout suivre"],
        "channels": ["linkedin", "x", "bluesky"],
        "price_eur": 9,
        "billing": "stripe",
        "agents": {"ads": False, "coder": False},
    },
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
    return sorted(
        p.parent.name for p in base.glob("*/company.yaml") if not p.parent.name.startswith(".")
    )


def load(path, slug: str | None = None) -> dict:
    """Read and normalise. Raises FileNotFoundError or ValueError; callers that
    want softer handling use validate() on the result."""
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(str(path))
    with open(path, encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)
    if raw is None:
        raw = {}  # an empty file is an empty company, not a crash
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
        price = None  # None is meaningful: the site reads "Let's talk"
    else:
        try:
            price = float(price)
            price = int(price) if float(price).is_integer() else price
            if price < 0:
                errors.append("offer.price_eur cannot be negative")
        except (TypeError, ValueError):
            errors.append(f"offer.price_eur: expected a number, got {offer_in['price_eur']!r}")
            price = None

    # What the buyer actually gets. Optional, and empty is a fine answer: the
    # generator used to print "Cancel anytime" and "Instant onboarding" on every
    # page it made, which are terms of sale nobody had agreed to. A short list
    # the operator wrote, or no list at all.
    includes = [str(i).strip() for i in (offer_in.get("includes") or []) if str(i).strip()]

    billing = str(offer_in.get("billing", "stripe")).strip().lower() or "stripe"
    if billing not in BILLING:
        warnings.append(
            f"offer.billing '{billing}' is not one of {', '.join(BILLING)}; kept as free text"
        )

    icp_in = raw.get("icp") or {}
    if not isinstance(icp_in, dict):
        warnings.append("icp was not a mapping; reset to defaults")
        icp_in = {}
    channels = [str(c).strip().lower() for c in (icp_in.get("channels") or []) if str(c).strip()]
    unknown = [c for c in channels if c not in CHANNELS]
    if unknown:
        warnings.append(
            f"icp.channels: dropped unknown {', '.join(unknown)} (known: {', '.join(CHANNELS)})"
        )
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
    # A tenth of the session budget was calibrated against mock runs, where a
    # turn costs a few hundred tokens. Against real providers one turn of one
    # agent runs three or four calls of a thousand tokens each, and the ticks of
    # several agents land in the same wall-clock minute — so a company created
    # with the old default froze on the circuit breaker six times in a single
    # session, measured. Half the session budget is the number that lets a real
    # quarter-day run; the session ceiling is still the thing that stops a
    # runaway, and it has not moved.
    default_tpm = max(20_000, session // 2)
    tpm = _int(budgets_in.get("tokens_per_minute", default_tpm), default_tpm)
    tpm = max(100, min(tpm, session))
    if tpm < 20_000 and "tokens_per_minute" in budgets_in:
        warnings.append(
            f"budgets.tokens_per_minute is {tpm}; a real provider spends that in one turn, "
            "so the circuit breaker will freeze the day. 20000 or more is a working floor."
        )
    # Opt-in, like the permission keys: emitting it always would pin every
    # company to whatever the global setting said the day it was created.
    cost_budget = None
    if "cost_budget" in budgets_in:
        try:
            cost_budget = max(0.0, float(budgets_in.get("cost_budget") or 0))
        except (TypeError, ValueError):
            warnings.append("budgets.cost_budget is not a number; the global setting applies")
    ads_eur = _int(budgets_in.get("daily_ad_spend_eur", 0), 0)
    if ads_eur < 0:
        warnings.append("budgets.daily_ad_spend_eur cannot be negative; set to 0")
        ads_eur = 0
    if ads_eur and not agents["ads"]:
        warnings.append("budgets.daily_ad_spend_eur is set but the ads agent is off")

    from .tools import TOOLS  # local import: tools imports config, config imports cfg

    hitl_in = raw.get("hitl_tools")
    hitl = [
        str(x).strip()
        for x in (hitl_in if isinstance(hitl_in, list) else DEFAULT_HITL)
        if str(x).strip()
    ]
    unknown_tools = [x for x in hitl if x not in TOOLS]
    if unknown_tools:
        warnings.append(f"hitl_tools: {', '.join(unknown_tools)} match no tool and gate nothing")

    # Permission overrides are opt-in and only written back when the operator
    # put them in the file. Emitting them always would pin every company to
    # whatever the global setting said the day it was created, and a later
    # change in the console would silently apply to nobody.
    perms: dict = {}
    if "permission_mode" in raw:
        mode = str(raw.get("permission_mode", "")).strip()
        if mode in permissions.MODES:
            perms["permission_mode"] = mode
        else:
            warnings.append(
                f"permission_mode: '{mode}' is not one of "
                f"{', '.join(permissions.MODES)}; the global setting applies"
            )
    if "ask_above" in raw:
        above = str(raw.get("ask_above", "")).strip()
        if above in permissions.RISK_CLASSES:
            perms["ask_above"] = above
        else:
            warnings.append(
                f"ask_above: '{above}' is not one of "
                f"{', '.join(permissions.RISK_CLASSES)}; the global setting applies"
            )
    if "auto_allow" in raw:
        raw_allow = raw.get("auto_allow")
        allow = [
            str(x).strip() for x in (raw_allow if isinstance(raw_allow, list) else []) if str(x)
        ]
        unknown_allow = [x for x in allow if x not in TOOLS]
        if unknown_allow:
            warnings.append(
                f"auto_allow: {', '.join(unknown_allow)} match no tool and allow nothing"
            )
        gated = [x for x in allow if x in hitl]
        if gated:
            warnings.append(
                f"auto_allow: {', '.join(gated)} are gated by name and stay gated; "
                "remove them from hitl_tools to auto-allow them"
            )
        declared = perms.get("permission_mode", "")
        if allow and declared and declared != permissions.CUSTOM:
            warnings.append(
                f"auto_allow is only honoured in custom permission mode, and this company "
                f"declares '{declared}'; the list does nothing"
            )
        perms["auto_allow"] = allow

    # The sales site's own block. `faq_app` names one of the company's apps
    # (companies/<slug>/apps/) run once at build time, its answers baked into
    # the static page. Normalised here rather than read raw in sitegen, because
    # a key that survives `load` only by accident is a key that disappears the
    # next time this dict is rebuilt.
    site_in = raw.get("site") or {}
    site: dict = {}
    if isinstance(site_in, dict):
        # Look. NullToHero's brand register puts it plainly: a centred stack of
        # icon-title-subtitle cards reads as template, and a generator with one
        # hard-coded look converges on exactly that. These two turn the page
        # without touching the copy.
        theme = str(site_in.get("theme", "")).strip().lower()
        if theme and theme not in ("light", "dark"):
            warnings.append(f"site.theme '{theme}' is not light or dark; using light")
            theme = ""
        if theme:
            site["theme"] = theme
        font = str(site_in.get("font", "")).strip().lower()
        if font and font not in ("serif", "sans"):
            warnings.append(f"site.font '{font}' is not serif or sans; using serif")
            font = ""
        if font:
            site["font"] = font
        accent = str(site_in.get("accent", "")).strip()
        if accent and not re.fullmatch(r"#[0-9a-fA-F]{6}", accent):
            warnings.append(f"site.accent '{accent}' is not a #rrggbb colour; using the default")
            accent = ""
        if accent:
            site["accent"] = accent
        faq_app = str(site_in.get("faq_app", "")).strip()
        faq = [str(q).strip() for q in (site_in.get("faq") or []) if str(q).strip()]
        if faq_app and not faq:
            warnings.append("site.faq_app names an app but site.faq lists no question")
        if faq and not faq_app:
            warnings.append("site.faq lists questions but site.faq_app names no app")
        if faq_app:
            site["faq_app"] = faq_app
        if faq:
            site["faq"] = faq
    elif site_in:
        errors.append("site: expected a mapping")

    # The language the company speaks. Not a display preference: it is written
    # into every agent's prompt and into the sales page, because a company whose
    # config is in French drafted "Thank you for contacting us" to its French
    # customers for want of anyone ever saying so. Declared wins; otherwise
    # guessed from what the operator typed, and the guess is written down where
    # they can see and fix it.
    declared = str(raw.get("language", "")).strip().lower()[:16]
    if declared and not re.fullmatch(r"[a-z]{2,3}(-[a-z0-9]{2,8})?", declared):
        warnings.append(f"language '{declared}' is not a language code like 'fr'; guessed instead")
        declared = ""
    language = declared or detect_language(
        " ".join(
            [name, str(raw.get("one_liner", "")), product, str(icp_in.get("segment", ""))] + pains
        )
    )

    cfg = {
        "slug": slug,
        "name": name,
        "language": language,
        "one_liner": str(raw.get("one_liner", "")).strip() or product,
        "offer": {
            "product": product,
            "price_eur": price,
            "billing": billing,
            "payment_link": str(offer_in.get("payment_link", "")).strip(),
            **({"includes": includes} if includes else {}),
        },
        "icp": {
            "segment": str(icp_in.get("segment", "")).strip() or "To be defined",
            "channels": channels,
            "pains": pains,
        },
        "agents": agents,
        "budgets": {
            "session_tokens": session,
            "tokens_per_minute": tpm,
            "daily_ad_spend_eur": ads_eur,
            **({"cost_budget": cost_budget} if cost_budget is not None else {}),
        },
        "hitl_tools": hitl,
        **({"site": site} if site else {}),
        **perms,
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
