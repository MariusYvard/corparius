"""Sales-site generator. One landing page built from a company config, as a
single self-contained HTML file (inline CSS, no build step, no external assets).
Where NullToHero is a broad design-and-audit toolkit, this is the straight-to-
the-point path: config in, a sellable page out, with a checkout CTA wired to a
Stripe payment link.

Two rules earn their place at the top of this module, because both were broken
in a page that shipped:

**The generator never publishes the model thinking out loud.** A real page went
out with `"Check-in, anonyme, en 90 secondes." Alternatively, a more punchy
version: "Mental Check-in en 90s"` as its H1. `clean_headline` below is the
gate; anything it refuses falls back to the value proposition in the config,
which a human wrote.

**The generator never writes a claim the company did not make.** The previous
version printed "Cancel anytime" and "Instant onboarding" in the pricing box of
every page it produced. Nobody had said either was true. Terms of sale are not
filler, and a generator has no business inventing them — so `offer.includes` is
read from the config or the list is simply absent.
"""

from __future__ import annotations

import hashlib
import html as _html
import logging
import os
import re

from . import cfg

log = logging.getLogger("corparius.sitegen")

# --------------------------------------------------------------------------
# The content contract
# --------------------------------------------------------------------------

MAX_HEADLINE = 120

# Phrases that mean the model is talking about the copy instead of writing it.
# Kept narrow on purpose: a headline is a rare, load-bearing string, and refusing
# a good one costs more than letting a mediocre one through. Every entry here was
# either observed in a real generation or is a refusal that must never reach a
# customer's page.
_META = re.compile(
    r"""(?ix)
      \b alternatively \b
    | \b here \s+ (?: is | are | ' s ) \s+ (?: a | an | the | some | two | three ) \b
        [^:]{0,40} \b (?: headline | version | option | tagline | title | line
                        | alternative | suggestion | variant | punchier ) \b
    | \b (?: option | version | variant | variante | proposition ) \s* \# ? \d
    | \b a \s+ more \s+ (?: punchy | concise | direct | catchy | aggressive | compelling ) \b
    | \b (?: voici | voil[àa] ) \s+ (?: un | une | le | la | les | quelques | deux | trois ) \b
    | \b (?: sinon | autre \s+ (?: version | option | proposition ) | ou \s+ bien ) \b
    | \b i \s* (?: would | ' d )? \s* (?: suggest | recommend | propose ) \b
    | \b (?: as \s+ an? \s+ (?: ai | language \s+ model ) | i \s+ cannot | i \s+ can ' t
           | i \s+ ' m \s+ sorry | i \s+ am \s+ sorry | en \s+ tant \s+ qu ' ia ) \b
    """
)

# Straight and curly, plus the guillemets a French model reaches for.
_QUOTED = re.compile(rf"[\"“”«»']\s*([^\"“”«»'\n]{{6,{MAX_HEADLINE}}})\s*[\"“”«»']")
_WRAPPERS = (('"', '"'), ("“", "”"), ("«", "»"), ("'", "'"), ("‘", "’"))


def _unwrap(text: str) -> str:
    """Peel symmetric quotes. A model asked for a headline very often answers
    with one in quotation marks, and the quotes then render inside the H1."""
    for _ in range(3):
        for opening, closing in _WRAPPERS:
            if len(text) > 2 and text.startswith(opening) and text.endswith(closing):
                text = text[len(opening) : -len(closing)].strip()
                break
        else:
            return text
    return text


def clean_headline(raw: str | None) -> str | None:
    """Return a headline fit for an H1, or None if there isn't one in `raw`.

    None is the honest answer, not a repaired string: the caller has the
    company's own value proposition to fall back on, and that is always better
    than a salvage attempt nobody reviewed.
    """
    text = " ".join(str(raw or "").split())
    if not text:
        return None

    # Two or more quoted runs is a menu of options, whatever prose surrounds it.
    # The first one is the model's own first choice, so it is the one to keep.
    quoted = _QUOTED.findall(text)
    if len(quoted) > 1 or (quoted and _META.search(text)):
        text = quoted[0].strip()
    elif _META.search(text):
        return None

    text = _unwrap(text).strip().strip("—–-").strip()
    if not text or len(text) > MAX_HEADLINE or _META.search(text):
        return None
    # A headline that is only punctuation, or that still carries a label like
    # "Headline:" at the front, is not a headline.
    text = re.sub(r"(?i)^\s*(headline|title|tagline|h1|titre|accroche)\s*:\s*", "", text).strip()
    if not re.search(r"[^\W\d_]{2}", text):
        return None
    return text


# --------------------------------------------------------------------------
# The page's own words
# --------------------------------------------------------------------------

# Section headings, the CTA and the billing note, per language. The company's
# content is whatever the operator and the agents wrote; this is the furniture
# around it, and it used to be English on every page regardless — `The problem`
# and `Pay as you go` sat above French copy on a French company's site.
#
# A language with no entry here keeps English furniture rather than a machine
# translation nobody can check. See company.LANGUAGES.
STRINGS: dict[str, dict[str, str]] = {
    "en": {
        "pricing": "Pricing",
        "problem": "The problem",
        "includes": "What you get",
        "faq": "Questions",
        "cta_buy": "Get started",
        "cta_talk": "Talk to us",
        "talk": "Let's talk",
        "oneoff": "one-off",
        "for": "For {segment}",
        "stripe": "Secure payment by Stripe",
        "built": "built with corparius",
    },
    "fr": {
        "pricing": "Tarif",
        "problem": "Le problème",
        "includes": "Ce que vous obtenez",
        "faq": "Questions fréquentes",
        "cta_buy": "Commencer",
        "cta_talk": "Nous contacter",
        "talk": "Parlons-en",
        "oneoff": "paiement unique",
        "for": "Pour {segment}",
        "stripe": "Paiement sécurisé par Stripe",
        "built": "créé avec corparius",
    },
    "es": {
        "pricing": "Precio",
        "problem": "El problema",
        "includes": "Qué incluye",
        "faq": "Preguntas frecuentes",
        "cta_buy": "Empezar",
        "cta_talk": "Hablemos",
        "talk": "Hablemos",
        "oneoff": "pago único",
        "for": "Para {segment}",
        "stripe": "Pago seguro con Stripe",
        "built": "creado con corparius",
    },
    "de": {
        "pricing": "Preis",
        "problem": "Das Problem",
        "includes": "Das bekommen Sie",
        "faq": "Häufige Fragen",
        "cta_buy": "Loslegen",
        "cta_talk": "Kontakt aufnehmen",
        "talk": "Sprechen wir",
        "oneoff": "einmalig",
        "for": "Für {segment}",
        "stripe": "Sichere Zahlung über Stripe",
        "built": "erstellt mit corparius",
    },
    "it": {
        "pricing": "Prezzo",
        "problem": "Il problema",
        "includes": "Cosa ottieni",
        "faq": "Domande frequenti",
        "cta_buy": "Inizia",
        "cta_talk": "Parliamone",
        "talk": "Parliamone",
        "oneoff": "pagamento unico",
        "for": "Per {segment}",
        "stripe": "Pagamento sicuro con Stripe",
        "built": "creato con corparius",
    },
    "pt": {
        "pricing": "Preço",
        "problem": "O problema",
        "includes": "O que está incluído",
        "faq": "Perguntas frequentes",
        "cta_buy": "Começar",
        "cta_talk": "Fale connosco",
        "talk": "Vamos conversar",
        "oneoff": "pagamento único",
        "for": "Para {segment}",
        "stripe": "Pagamento seguro com Stripe",
        "built": "criado com corparius",
    },
    "nl": {
        "pricing": "Prijs",
        "problem": "Het probleem",
        "includes": "Wat je krijgt",
        "faq": "Veelgestelde vragen",
        "cta_buy": "Aan de slag",
        "cta_talk": "Neem contact op",
        "talk": "Laten we praten",
        "oneoff": "eenmalig",
        "for": "Voor {segment}",
        "stripe": "Veilig betalen met Stripe",
        "built": "gemaakt met corparius",
    },
}


def strings(language: str) -> dict[str, str]:
    """The furniture for `language`, falling back to English word by word so a
    partially-filled entry can never render an empty heading."""
    code = str(language or "en").strip().lower().split("-")[0]
    return {**STRINGS["en"], **STRINGS.get(code, {})}


# --------------------------------------------------------------------------
# The look
# --------------------------------------------------------------------------

# The default was a dark page with gradient pills and a centred stack of three
# cards. NullToHero's brand register names that shape exactly — "a centred-stack
# hero with icon-title-subtitle cards reads as template" — and it was right: the
# page announced that a machine had made it.
#
# What replaces it: a left-aligned asymmetric hero, a modular type scale at a
# 1.333 ratio (a flat scale "reads as uncommitted"), hierarchy carried by weight
# and rules rather than colour, and one CTA repeated instead of several
# competing. Typeface is a system stack in both registers — an external font
# would cost this page the one property it has always defended, that it is a
# single file that needs nothing.
_SERIF = '"Iowan Old Style","Palatino Linotype",Palatino,"Book Antiqua",Georgia,serif'
_SANS = '-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif'
_THEMES = {
    "light": {
        "bg": "#fbfaf8",
        "fg": "#14110e",
        "muted": "#5f574e",
        "line": "#e5ded3",
        "ink": "#14110e",
    },
    "dark": {
        "bg": "#12100e",
        "fg": "#f3eee6",
        "muted": "#a49b8e",
        "line": "#2b2722",
        # Inverting a dark page means going lighter, not darker: the pricing
        # band has to be a change of ground, and #000 on #12100e is not one.
        "ink": "#241f1a",
    },
}
DEFAULT_ACCENT = "#c2410c"


def signature(seed: str) -> str:
    """A band of bars whose heights come from a hash of the company's own name.

    Every page gets a different one and it is the same every build, which is the
    point: a landing page needs something on it that is not a paragraph, and the
    alternatives were a stock photo this generator cannot fetch, a gradient blob
    that announces which decade of template it came from, or nothing — and
    nothing is what made the last version read as an unfinished document.

    Inline SVG, about a kilobyte, no request, no asset, no script.
    """
    digest = hashlib.sha256(seed.encode("utf-8")).digest()
    bars, count, width = [], 56, 1000 / 56
    for i in range(count):
        value = digest[i % len(digest)]
        # Taller towards the middle, so the band has a shape rather than being
        # uniform noise. The hash decides the texture; the curve decides the form.
        curve = 1 - abs((i / (count - 1)) - 0.5) * 1.55
        height = max(6.0, (10 + value / 255 * 90) * curve)
        opacity = 0.16 + (value % 7) * 0.055
        bars.append(
            f'<rect x="{i * width:.2f}" y="{100 - height:.2f}" width="{width * 0.62:.2f}" '
            f'height="{height:.2f}" opacity="{opacity:.2f}"/>'
        )
    return (
        '<svg class="sig" viewBox="0 0 1000 100" preserveAspectRatio="none" '
        f'aria-hidden="true" focusable="false"><g fill="currentColor">{"".join(bars)}</g></svg>'
    )


def css(theme: str = "light", font: str = "serif", accent: str = DEFAULT_ACCENT) -> str:
    palette = _THEMES.get(theme, _THEMES["light"])
    display = _SERIF if font == "serif" else _SANS
    # A serif display carries its own voice; a sans one has to earn the same
    # contrast through tracking and weight, or the page reads as unstyled.
    display_style = (
        "letter-spacing:-.01em;font-weight:600" if font == "serif" else "letter-spacing:-.03em"
    )
    # Light type on a dark ground reads lighter than it is and wants more room.
    lift = ".08" if theme == "dark" else "0"
    return f"""
:root{{
  --bg:{palette["bg"]};--fg:{palette["fg"]};--muted:{palette["muted"]};
  --line:{palette["line"]};--accent:{accent};--ink:{palette["ink"]};
  --f0:1.0625rem;--f1:1.42rem;--f2:1.9rem;--f3:2.53rem;
  --h1:clamp(3rem,8.4vw,5.6rem);
  --gap:clamp(64px,10vw,132px);
  --display:{display};--body:{_SANS};
  /* The accent, thinned. Every tint on the page is this one colour at a
     different strength — which is what makes a palette read as chosen rather
     than assembled. */
  --wash:color-mix(in srgb,var(--accent) {"14" if theme == "dark" else "9"}%,var(--bg));
  --edge:color-mix(in srgb,var(--accent) 26%,var(--bg));
}}
*{{box-sizing:border-box}}
html{{-webkit-text-size-adjust:100%}}
body{{margin:0;background:var(--bg);color:var(--fg);font-family:var(--body);
  font-size:var(--f0);line-height:calc(1.6 + {lift});
  -webkit-font-smoothing:antialiased;text-rendering:optimizeLegibility}}
a{{color:inherit}}
h1,h2,h3{{font-family:var(--display);{display_style};line-height:1.05;margin:0;
  text-wrap:balance}}
p{{margin:0;max-width:62ch}}
.wrap{{max-width:1120px;margin:0 auto;padding:0 clamp(20px,5vw,52px)}}

/* Full-bleed bands. The page reads as composed rather than typed because it
   changes ground three times — washed, plain, inverted — and each change lands
   on a section boundary. */
.band{{position:relative;overflow:hidden}}
.band-hero{{background:var(--wash);border-bottom:1px solid var(--edge)}}
.band-dark{{background:var(--ink);color:{palette["bg"]}}}

header{{display:flex;align-items:baseline;justify-content:space-between;gap:20px;
  padding:26px 0;flex-wrap:wrap}}
.logo{{font-family:var(--display);font-size:var(--f1);font-weight:700;
  letter-spacing:-.02em}}
.nav{{color:var(--muted);font-size:.94rem;text-decoration:none;
  border-bottom:1px solid var(--edge);padding-bottom:2px}}
.nav:hover{{color:var(--accent);border-color:var(--accent)}}

/* Asymmetric on purpose. The old hero centred everything, which is the one
   layout that cannot express emphasis: when all of it is in the middle, none
   of it is anywhere. */
.hero{{position:relative;z-index:1;padding:clamp(56px,10vw,120px) 0
  clamp(72px,12vw,150px)}}
.hero h1{{font-size:var(--h1);max-width:15ch;margin:0 0 clamp(22px,3vw,32px)}}
.lede{{font-size:var(--f1);color:var(--muted);max-width:44ch;
  margin:0 0 clamp(30px,4vw,44px);line-height:1.42}}
.facts{{display:flex;flex-wrap:wrap;gap:12px 30px;margin-top:30px;
  font-size:.92rem;color:var(--muted)}}
.facts span{{display:inline-flex;align-items:center;gap:9px}}
.facts span::before{{content:"";width:6px;height:6px;border-radius:50%;
  background:var(--accent);flex:none}}

/* The signature: bars whose heights come from a hash of the company name, so
   two companies never get the same hero edge and one company always gets its
   own. It sits under the text and is decorative — aria-hidden in the markup. */
.sig{{position:absolute;left:0;right:0;bottom:-1px;width:100%;
  height:clamp(120px,20vw,230px);color:var(--accent);z-index:0;
  pointer-events:none}}

.btn{{display:inline-block;background:var(--accent);color:#fff;
  padding:17px 34px;border-radius:2px;font-weight:600;font-size:1.05rem;
  border:0;cursor:pointer;text-decoration:none;letter-spacing:.01em;
  box-shadow:0 1px 0 color-mix(in srgb,var(--accent) 60%,#000);
  transition:transform .12s ease,filter .12s ease,box-shadow .12s ease}}
.btn:hover{{filter:brightness(1.07);transform:translateY(-2px);
  box-shadow:0 3px 0 color-mix(in srgb,var(--accent) 60%,#000)}}
.btn:active{{transform:translateY(0);box-shadow:0 1px 0
  color-mix(in srgb,var(--accent) 60%,#000)}}
.btn:focus-visible{{outline:3px solid var(--accent);outline-offset:4px}}

section{{padding:var(--gap) 0}}
section+section{{padding-top:0}}
/* An eyebrow rule above each heading. Two characters of structure, and the page
   stops being an undifferentiated column of text. */
section h2{{font-size:var(--f2);margin:0 0 clamp(26px,3.5vw,40px);max-width:22ch;
  padding-top:20px;border-top:3px solid var(--accent);display:inline-block}}
.rule{{display:none}}
/* The full description, set as running text rather than crammed under the H1.
   Larger than body copy because it is the first real reading on the page. */
.story p{{font-size:var(--f1);line-height:1.5;max-width:56ch;color:var(--muted)}}
.story p::first-line{{color:var(--fg)}}
/* A long `icp.segment` is a sentence about who this is for, so it is set as
   one — large, narrow, its own beat, in the display face. */
.who-sec .who{{font-family:var(--display);font-size:clamp(1.5rem,3.4vw,2.1rem);
  max-width:26ch;line-height:1.25;color:var(--fg);
  border-left:3px solid var(--accent);padding-left:clamp(20px,3vw,32px)}}

/* A list, not cards. Three pains in three boxes is decoration; three pains one
   under another, each on its own line with air, is an argument. */
.pains{{list-style:none;padding:0;margin:0;max-width:54ch}}
.pains li{{padding:22px 0 22px 34px;border-top:1px solid var(--line);
  font-size:var(--f1);line-height:1.38;position:relative}}
.pains li:last-child{{border-bottom:1px solid var(--line)}}
.pains li::before{{content:"";position:absolute;left:0;top:34px;width:18px;
  height:2px;background:var(--accent)}}

.gets{{list-style:none;padding:0;margin:0;display:grid;gap:4px 44px;
  grid-template-columns:repeat(auto-fit,minmax(280px,1fr))}}
.gets li{{padding:15px 0 15px 30px;position:relative;color:var(--muted)}}
.gets li::before{{content:"";position:absolute;left:0;top:24px;width:14px;
  height:2px;background:var(--accent)}}

/* The price is the loudest number on the page, on the one band that inverts.
   A sales page whose price is set at body weight has hidden its own argument. */
.band-dark section h2{{border-top-color:var(--accent)}}
.price{{display:flex;flex-wrap:wrap;align-items:flex-end;
  gap:clamp(28px,6vw,72px);margin:0}}
.amt{{font-family:var(--display);font-size:clamp(3.4rem,10vw,6rem);
  font-weight:700;line-height:.9;letter-spacing:-.035em;
  font-variant-numeric:tabular-nums}}
.per{{color:color-mix(in srgb,{palette["bg"]} 62%,transparent);font-size:.95rem;
  margin-top:14px;letter-spacing:.04em;text-transform:uppercase}}

.faq{{display:grid;gap:0;max-width:64ch}}
.faq details{{border-top:1px solid var(--line);padding:20px 0}}
.faq details:last-of-type{{border-bottom:1px solid var(--line)}}
.faq summary{{font-family:var(--display);font-size:var(--f1);cursor:pointer;
  list-style:none;font-weight:600;display:flex;justify-content:space-between;
  gap:20px;align-items:baseline}}
.faq summary::-webkit-details-marker{{display:none}}
.faq summary::after{{content:"+";color:var(--accent);font-weight:400;flex:none}}
.faq details[open] summary::after{{content:"–"}}
.faq summary:focus-visible{{outline:2px solid var(--accent);outline-offset:4px}}
.faq p{{color:var(--muted);margin-top:14px}}

.close{{padding:var(--gap) 0 calc(var(--gap) * .7)}}
.close h2{{font-size:clamp(2rem,5vw,3.2rem);margin-bottom:34px;max-width:18ch;
  border:0;padding-top:0}}
footer{{padding:0 0 60px;color:var(--muted);font-size:.88rem;
  display:flex;gap:10px;align-items:center}}
footer::before{{content:"";width:22px;height:2px;background:var(--accent);
  flex:none}}

@media(prefers-reduced-motion:reduce){{*{{transition:none!important}}}}
"""


def _esc(value) -> str:
    return _html.escape(str(value))


def _norm(text: str) -> str:
    """Loose comparison, for deciding whether two strings say the same thing."""
    return re.sub(r"[^\w]+", " ", str(text or "").lower()).strip()


def _opening(text: str, limit: int = 190) -> str:
    """The first sentence or two, up to `limit`, cut on a sentence boundary.

    `offer.product` is a description, not a strapline: vigil's is 500 characters
    covering the protocol, the on-device analysis and the founder's background.
    All of it is worth reading and none of it belongs at 1.4rem under an H1, so
    the opening goes in the hero and the whole thing gets its own paragraph
    further down. Nothing is thrown away and nothing is cut mid-word.
    """
    text = " ".join(str(text or "").split())
    if len(text) <= limit:
        return text
    # Whole sentences, greedily, while they fit. Taking the *last* boundary
    # under the limit is the obvious version and it is wrong: a short opening
    # sentence followed by a long one returns the stub and drops the rest.
    kept = ""
    for sentence in re.findall(r"[^.!?]*[.!?]+(?:\s|$)|[^.!?]+$", text):
        if kept and len(kept) + len(sentence) > limit:
            break
        kept += sentence
    kept = kept.strip()
    if kept and len(kept) <= limit:
        return kept
    # No sentence break in reach: cut on a word, and say so.
    cut = text[: limit + 1]
    space = cut.rfind(" ")
    return (cut[:space] if space > 0 else cut[:limit]).rstrip(" ,;:—–-") + "…"


# --------------------------------------------------------------------------
# The page
# --------------------------------------------------------------------------


def faq_pairs(company: dict, store) -> list[tuple[str, str]]:
    """Ask one of the company's own apps the questions listed in company.yaml.

    The page stays a single static file: the answers are baked in at build time,
    so there is no JavaScript on it, no endpoint for it to reach, and nothing
    left running. That is the property this generator has defended from the
    start, and a chat widget would have traded it away for a feature nobody
    asked for.

        site:
          faq_app: faq
          faq: ["How much is it?", "Who is it for?"]

    A model that cannot be reached returns [] and the section is simply absent.
    A page that fails to build because a free provider hiccuped would be a bad
    trade for a FAQ.
    """
    from . import apps as apps_mod

    site = company.get("site") or {}
    name = site.get("faq_app")
    questions = [str(q).strip() for q in (site.get("faq") or []) if str(q).strip()]
    if not name or not questions or store is None:
        return []
    slug = company.get("slug", "")
    app = apps_mod.get(slug, str(name))
    if app is None:
        log.warning("site FAQ names app '%s', which %s does not have", name, slug or "this company")
        return []
    pairs: list[tuple[str, str]] = []
    for question in questions:
        result = apps_mod.run(app, slug, store, question, company)
        if not result["ok"]:
            log.warning("site FAQ: no model answered '%s'; section omitted", question)
            return []
        pairs.append((question, result["text"]))
    return pairs


def faq_html(company: dict, store) -> str:
    """Kept for callers that want the fragment on its own."""
    pairs = faq_pairs(company, store)
    if not pairs:
        return ""
    txt = strings(company.get("language", "en"))
    items = "".join(
        f"<details><summary>{_esc(q)}</summary><p>{_esc(a)}</p></details>" for q, a in pairs
    )
    return f'<section id="faq"><h2>{_esc(txt["faq"])}</h2><div class="faq">{items}</div></section>'


def build_site(company: dict, out_dir: str, headline: str | None = None, store=None) -> str:
    """Render a single-file sales page for `company` into out_dir/index.html.

    `store` is only needed for the generated FAQ (see `faq_pairs`); without it
    the page is exactly what it was before, which is what every caller that has
    no store should get.
    """
    name = company.get("name", "Your product")
    offer = company.get("offer", {}) or {}
    icp = company.get("icp", {}) or {}
    site = company.get("site", {}) or {}
    language = str(company.get("language") or "en")
    txt = strings(language)

    product = str(offer.get("product", "")).strip()
    segment = str(icp.get("segment", "")).strip()
    price = offer.get("price_eur")
    billing = str(offer.get("billing", "")).strip()
    pains = [str(p).strip() for p in (icp.get("pains") or []) if str(p).strip()]
    includes = [str(i).strip() for i in (offer.get("includes") or []) if str(i).strip()]
    pay = offer.get("payment_link") or cfg.get("CORP_STRIPE_PAYMENT_LINK", "")

    one_liner = " ".join(str(company.get("one_liner") or product).split())
    # The contract. A refused headline is not an error: the config's own value
    # proposition is a sentence a person wrote, which is a better H1 than a
    # rescued fragment of one the model was still deliberating over.
    head = clean_headline(headline)
    if headline and head is None:
        log.warning(
            "site: the drafted headline was refused (model meta-commentary or too long); "
            "falling back to the company's one-liner"
        )
    if head is None:
        head = clean_headline(one_liner) or name

    # The lede must not simply repeat the H1 back at the reader, and must not be
    # a description either — see _opening.
    lede = _opening(one_liner if _norm(one_liner) != _norm(head) else product)
    if _norm(lede) == _norm(head):
        lede = ""
    # Whatever the lede could not carry, in full, in its own paragraph. Real
    # content the previous version simply never rendered.
    story = product if len(product) > len(lede) and _norm(product) != _norm(lede) else ""

    cta_label = txt["cta_buy"] if pay else txt["cta_talk"]
    cta_href = pay or "#pricing"
    cta = f'<a class="btn" href="{_esc(cta_href)}">{_esc(cta_label)}</a>'

    price_txt = f"{_esc(price)} EUR" if price is not None else _esc(txt["talk"])
    # Facts, not claims: every one of these is a value the operator typed.
    facts = []
    # `icp.segment` is a positioning field, not a label: vigil's is 200
    # characters of who it serves and who prescribes it. That is the right thing
    # to write there and the wrong thing to put in a chip beside the price, so a
    # long one is left out rather than cut mid-sentence with an ellipsis.
    if segment and len(segment) <= 64:
        facts.append(txt["for"].format(segment=segment))
    if price is not None:
        facts.append(f"{price} EUR")
    if billing == "stripe" and pay:
        facts.append(txt["stripe"])
    facts_html = (
        '<div class="facts">' + "".join(f"<span>{_esc(f)}</span>" for f in facts) + "</div>"
        if facts
        else ""
    )
    # ...and it is not thrown away either. Who a product is for is real content;
    # it just belongs in a sentence rather than in a chip.
    who = segment if segment and len(segment) > 64 else ""
    who_html = f'<p class="who">{_esc(txt["for"].format(segment=who))}</p>' if who else ""

    # A section with nothing real in it is left out entirely rather than filled
    # with a template. That is why these are appended conditionally and joined
    # at the end: an empty "Why it works" used to render three cards of
    # corparius's own marketing copy on somebody else's page.
    parts = []
    if story:
        parts.append(f'<section class="story"><p>{_esc(story)}</p></section>')
    if who_html:
        parts.append(f'<section class="who-sec">{who_html}</section>')
    if pains:
        items = "".join(f"<li>{_esc(p)}</li>" for p in pains)
        parts.append(
            f'<section><h2>{_esc(txt["problem"])}</h2><ul class="pains">{items}</ul></section>'
        )
    if includes:
        items = "".join(f"<li>{_esc(i)}</li>" for i in includes)
        parts.append(
            f'<section><h2>{_esc(txt["includes"])}</h2><ul class="gets">{items}</ul></section>'
        )
    body_html = "".join(p for p in parts if p)
    if body_html:
        body_html = f'<div class="band"><div class="wrap">{body_html}</div></div>'

    # The price gets the one band that inverts. It is the number the whole page
    # is arguing towards, and the previous version set it at 2.4rem inside a
    # grey box, which is where you put a number you would rather not mention.
    pricing = (
        f'<div class="band band-dark"><div class="wrap">'
        f'<section id="pricing"><h2>{_esc(txt["pricing"])}</h2>'
        f'<div class="price"><div><div class="amt">{price_txt}</div>'
        f'<div class="per">{_esc(billing or txt["oneoff"])}</div></div>{cta}</div>'
        f"</section></div></div>"
    )
    faq = faq_html(company, store)
    if faq:
        faq = f'<div class="band"><div class="wrap">{faq}</div></div>'

    # The closing block repeats the CTA, not the H1. A page that ends by saying
    # its own headline again word for word has stopped making an argument — but
    # a closing heading is a heading, so anything long goes back to the H1
    # rather than setting a paragraph at 3rem.
    closer = lede if lede and _norm(lede) != _norm(head) and len(lede) <= 90 else head

    doc = f"""<!doctype html>
<html lang="{_esc(language)}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_esc(name)} — {_esc(lede or head)}</title>
<meta name="description" content="{_esc(lede or head)}">
<meta property="og:title" content="{_esc(name)}">
<meta property="og:description" content="{_esc(lede or head)}">
<style>{
        css(
            site.get("theme", "light"),
            site.get("font", "serif"),
            site.get("accent", DEFAULT_ACCENT),
        )
    }</style>
</head>
<body>
<div class="band band-hero">
  <div class="wrap">
    <header>
      <div class="logo">{_esc(name)}</div>
      <a class="nav" href="#pricing">{_esc(txt["pricing"])}</a>
    </header>
    <div class="hero">
      <h1>{_esc(head)}</h1>
      {f'<p class="lede">{_esc(lede)}</p>' if lede else ""}
      {cta}
      {facts_html}
    </div>
  </div>
  {signature(company.get("slug") or name)}
</div>
{body_html}
{pricing}
{faq}
<div class="band">
  <div class="wrap">
    <div class="close">
      <h2>{_esc(closer)}</h2>
      {cta}
    </div>
    <footer>{_esc(name)} · {_esc(txt["built"])}</footer>
  </div>
</div>
</body>
</html>"""

    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "index.html")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(doc)
    return path
