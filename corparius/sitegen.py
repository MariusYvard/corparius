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
import json
import logging
import os
import re
from pathlib import Path

from . import cfg
from .kernel import text

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
        "how": "How it works",
        "proof": "What this rests on",
        "voices": "What people say",
        "privacy": "Your data",
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
        "how": "Comment ça marche",
        "proof": "Sur quoi ça repose",
        "voices": "Ce qu'ils en disent",
        "privacy": "Vos données",
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
        "how": "Cómo funciona",
        "proof": "En qué se basa",
        "voices": "Lo que dicen",
        "privacy": "Tus datos",
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
        "how": "So funktioniert es",
        "proof": "Worauf es beruht",
        "voices": "Stimmen",
        "privacy": "Ihre Daten",
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
        "how": "Come funziona",
        "proof": "Su cosa si basa",
        "voices": "Cosa dicono",
        "privacy": "I tuoi dati",
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
        "how": "Como funciona",
        "proof": "Em que se baseia",
        "voices": "O que dizem",
        "privacy": "Os seus dados",
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
        "how": "Hoe het werkt",
        "proof": "Waarop het rust",
        "voices": "Wat men zegt",
        "privacy": "Jouw gegevens",
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


# --------------------------------------------------------------------------
# Contrast, computed rather than assumed
# --------------------------------------------------------------------------

# The dark theme's pricing band shipped with its text at 1.16:1 against its own
# background — near-black on near-black, unreadable, and visible in a screenshot
# the moment anyone looked. The cause was one line assuming that "the page
# background colour" is always a good text colour on "the inverted band", which
# is true in the light theme and false in the dark one.
#
# Nothing in this repo could have caught that, because no code here knew what
# contrast was. Now it does, and `tests/test_sitegen_contrast.py` walks every
# theme against every accent and fails on anything under the threshold.
#
# Thresholds are WCAG 2.1 AA, as listed in NullToHero's color-and-contrast
# reference: 4.5 for body text, 3.0 for large text and UI components.
AA_TEXT, AA_LARGE = 4.5, 3.0


def _rgb(colour: str) -> tuple[int, int, int]:
    value = colour.lstrip("#")
    if len(value) == 3:
        value = "".join(c * 2 for c in value)
    return (int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16))


def luminance(colour: str) -> float:
    """WCAG relative luminance."""

    def channel(raw: int) -> float:
        c = raw / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = (channel(c) for c in _rgb(colour))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a: str, b: str) -> float:
    """WCAG contrast ratio, 1.0 to 21.0."""
    high, low = sorted((luminance(a), luminance(b)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def mix(a: str, b: str, amount: float) -> str:
    """`a` blended `amount` of the way towards `b`, as a hex string.

    Done here rather than with CSS `color-mix` so the result is a value this
    module can measure. A colour the code cannot read is a colour no test can
    check, which is how the unreadable band shipped.
    """
    ra, ga, ba = _rgb(a)
    rb, gb, bb = _rgb(b)
    blend = (round(x + (y - x) * amount) for x, y in ((ra, rb), (ga, gb), (ba, bb)))
    return "#" + "".join(f"{c:02x}" for c in blend)


def readable_on(background: str, *candidates: str, target: float = AA_TEXT) -> str:
    """The first candidate that clears `target` against `background`.

    If none does, the best of black and white — which always clears 4.5 against
    anything, so this never returns something unreadable.
    """
    for candidate in candidates:
        if contrast(candidate, background) >= target:
            return candidate
    return max(("#ffffff", "#0a0a0a"), key=lambda c: contrast(c, background))


def muted_on(background: str, text: str, target: float = AA_TEXT) -> str:
    """`text` faded towards `background` as far as it can go and still be read.

    Secondary text has to look secondary without becoming decoration. Walking
    the blend back until it clears the threshold gets that without a hand-picked
    grey per theme — and their own reference is blunt about the alternative:
    "Alpha Is A Design Smell", because alpha makes contrast unpredictable.
    """
    for step in range(60, -1, -5):
        candidate = mix(text, background, step / 100)
        if contrast(candidate, background) >= target:
            return candidate
    return text


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


def palette_for(theme: str = "light", accent: str = DEFAULT_ACCENT) -> dict[str, str]:
    """Every colour the page uses, each one measured against what it sits on.

    Returned as a dict so a test can walk it. The four derived entries are the
    ones that used to be assumed:

    - `on_ink` — text on the inverted pricing band. Assuming the page background
      worked here is the bug that shipped at 1.16:1.
    - `on_accent` — the button label. `#fff` was hard-coded, which fails on any
      light accent: 1.74:1 on the green in the operator's screenshot.
    - `muted`, `on_ink_muted` — secondary text, faded only as far as it can be.
    - `wash` — the hero band's ground, computed rather than `color-mix`, so the
      text on it can be measured too.
    """
    base = _THEMES.get(theme, _THEMES["light"])
    bg, fg, ink = base["bg"], base["fg"], base["ink"]
    on_ink = readable_on(ink, bg, fg, target=AA_TEXT)
    return {
        **base,
        "accent": accent,
        # The accent tint behind the hero, strong enough to read as a change of
        # ground and weak enough to keep the body text on it.
        "wash": mix(bg, accent, 0.14 if theme == "dark" else 0.09),
        "edge": mix(bg, accent, 0.26),
        "muted": base["muted"] if contrast(base["muted"], bg) >= AA_TEXT else muted_on(bg, fg),
        "on_ink": on_ink,
        "on_ink_muted": muted_on(ink, on_ink),
        "on_accent": readable_on(accent, "#ffffff", "#0a0a0a"),
        # The button's bottom edge. Decorative, but resolved here too so
        # that nothing on the page is a colour this module cannot read.
        "accent_deep": mix(accent, "#000000", 0.4),
    }


def css(theme: str = "light", font: str = "serif", accent: str = DEFAULT_ACCENT) -> str:
    palette = palette_for(theme, accent)
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
     than assembled. Every value here is resolved before it is written, so a
     test can measure exactly what a visitor sees. */
  --wash:{palette["wash"]};
  --edge:{palette["edge"]};
  /* Text on grounds that are not --bg. Every one of these is checked against
     WCAG AA before it reaches the page; see palette_for(). */
  --on-ink:{palette["on_ink"]};
  --on-ink-muted:{palette["on_ink_muted"]};
  --on-accent:{palette["on_accent"]};
  --accent-deep:{palette["accent_deep"]};
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
.band-dark{{background:var(--ink);color:var(--on-ink)}}

/* Landmarks, not divs: header / main / footer are how a screen reader and a
   crawler find their way around a page. The banner used to live inside the hero
   band, which made it a section header rather than the page's. */
.topbar .wrap{{display:flex;align-items:baseline;justify-content:space-between;
  gap:20px;padding:26px clamp(20px,5vw,52px);flex-wrap:wrap}}
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

.btn{{display:inline-block;background:var(--accent);color:var(--on-accent);
  padding:17px 34px;border-radius:2px;font-weight:600;font-size:1.05rem;
  border:0;cursor:pointer;text-decoration:none;letter-spacing:.01em;
  box-shadow:0 1px 0 var(--accent-deep);
  transition:transform .12s ease,filter .12s ease,box-shadow .12s ease}}
.btn:hover{{filter:brightness(1.07);transform:translateY(-2px);
  box-shadow:0 3px 0 var(--accent-deep)}}
.btn:active{{transform:translateY(0);box-shadow:0 1px 0 var(--accent-deep)}}
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
.per{{color:var(--on-ink-muted);font-size:.95rem;
  margin-top:14px;letter-spacing:.04em;text-transform:uppercase}}

/* The protocol. Numbered because these are genuinely sequential — a check-in
   that happens after the analysis is a different product — which is the one
   case where a numeral carries information rather than decorating. */
.how{{list-style:none;padding:0;margin:0;counter-reset:s;display:grid;gap:0;
  max-width:58ch}}
.how li{{display:flex;gap:18px;align-items:baseline;padding:20px 0;
  border-top:1px solid var(--line);font-size:var(--f1);line-height:1.4}}
.how li:last-child{{border-bottom:1px solid var(--line)}}
.step-n{{font-family:var(--display);font-size:var(--f2);color:var(--accent);
  font-weight:700;line-height:1;flex:none;min-width:1.2em}}

/* A claim and where it comes from, on the same line. The source is not a
   footnote here: it is the reason the claim is allowed on the page at all. */
.proof{{list-style:none;padding:0;margin:0;max-width:62ch;display:grid;gap:0}}
.proof li{{padding:18px 0;border-top:1px solid var(--line);display:grid;gap:4px}}
.proof li:last-child{{border-bottom:1px solid var(--line)}}
.claim{{font-size:var(--f1);line-height:1.4}}
.source{{color:var(--muted);font-size:.88rem}}

.voices{{display:grid;gap:22px;grid-template-columns:repeat(auto-fit,minmax(280px,1fr))}}
.voices figure{{margin:0;padding:24px;border:1px solid var(--line);border-radius:10px}}
.voices blockquote{{margin:0;font-family:var(--display);font-size:var(--f1);
  line-height:1.4}}
.voices figcaption{{margin-top:14px;color:var(--muted);font-size:.9rem}}
.voices figcaption::before{{content:"— "}}

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
footer .wrap{{padding-bottom:60px;color:var(--muted);font-size:.88rem;
  display:flex;gap:10px;align-items:center}}
footer .wrap::before{{content:"";width:22px;height:2px;background:var(--accent);
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


# --------------------------------------------------------------------------
# What a search engine needs, which is not on the page
# --------------------------------------------------------------------------


def head_tags(company: dict, title: str, description: str, faq: list) -> str:
    """Canonical link, social cards and structured data.

    A landing page nobody can find is a landing page nobody buys from, and this
    generator was emitting four meta tags. The rest is here.

    Everything absolute — the canonical, `og:url`, the sitemap entry — needs
    `site.url`, which the operator sets once after hosting. Without it those
    tags are omitted rather than pointed at a guess, because a canonical link to
    the wrong address is worse for a site than no canonical link at all.
    """
    site = company.get("site") or {}
    url = str(site.get("url") or "").rstrip("/")
    name = company.get("name", "")
    language = str(company.get("language") or "en")
    offer = company.get("offer") or {}
    price = offer.get("price_eur")

    tags = [
        f'<meta name="description" content="{_esc(description)}">',
        '<meta name="robots" content="index,follow,max-image-preview:large">',
        f'<meta property="og:type" content="{"product" if price is not None else "website"}">',
        f'<meta property="og:site_name" content="{_esc(name)}">',
        f'<meta property="og:title" content="{_esc(title)}">',
        f'<meta property="og:description" content="{_esc(description)}">',
        f'<meta property="og:locale" content="{_esc(language.replace("-", "_"))}">',
        '<meta name="twitter:card" content="summary_large_image">',
        f'<meta name="twitter:title" content="{_esc(title)}">',
        f'<meta name="twitter:description" content="{_esc(description)}">',
    ]
    if url:
        tags.insert(0, f'<link rel="canonical" href="{_esc(url)}/">')
        tags.append(f'<meta property="og:url" content="{_esc(url)}/">')

    # Structured data. `Product` with an `Offer` is what turns a price into a
    # rich result; `FAQPage` does the same for questions the page already
    # answers. Emitted only from values the config actually holds — a schema
    # block claiming a rating nobody left is the machine-readable version of
    # inventing "Cancel anytime".
    graph: list[dict] = []
    product: dict = {
        "@type": "Product",
        "name": name,
        "description": description,
    }
    if url:
        product["url"] = f"{url}/"
    if price is not None:
        product["offers"] = {
            "@type": "Offer",
            "price": str(price),
            "priceCurrency": "EUR",
            "availability": "https://schema.org/InStock",
            **({"url": str(offer.get("payment_link"))} if offer.get("payment_link") else {}),
        }
    graph.append(product)
    if faq:
        graph.append(
            {
                "@type": "FAQPage",
                "mainEntity": [
                    {
                        "@type": "Question",
                        "name": question,
                        "acceptedAnswer": {"@type": "Answer", "text": answer},
                    }
                    for question, answer in faq
                ],
            }
        )
    payload = json.dumps(
        {"@context": "https://schema.org", "@graph": graph}, ensure_ascii=False, indent=None
    )
    # This block carries model output — the FAQ answers — into a <script>
    # element, where HTML escaping is wrong because it would corrupt the JSON.
    #
    # Escaping only `</script>` is the usual advice and it is reasoning about
    # HTML parser states, which is where XSS lives. Escaping `<`, `>` and `&` as
    # JSON unicode escapes is valid JSON, decodes to the identical string for
    # every consumer, and leaves nothing in the block that a parser could read
    # as markup at all. No edge case to be wrong about.
    payload = payload.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    tags.append(f'<script type="application/ld+json">{payload}</script>')
    return "\n".join(tags)


def companions(company: dict) -> dict[str, str]:
    """robots.txt and sitemap.xml, keyed by filename.

    Both need an absolute address, so both are absent until `site.url` is set —
    a sitemap listing `/` with no host tells a crawler nothing, and a robots.txt
    pointing at a sitemap that is not there is worse than none.
    """
    url = str((company.get("site") or {}).get("url") or "").rstrip("/")
    if not url:
        return {}
    return {
        "robots.txt": f"User-agent: *\nAllow: /\n\nSitemap: {url}/sitemap.xml\n",
        "sitemap.xml": (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
            f"  <url><loc>{_esc(url)}/</loc><changefreq>weekly</changefreq>"
            "<priority>1.0</priority></url>\n"
            # Every secondary page too: one that no sitemap lists is one no
            # crawler is told about, which is most of the point of having it.
            + "".join(
                f"  <url><loc>{_esc(url)}/{pg['slug']}.html</loc>"
                "<changefreq>monthly</changefreq><priority>0.6</priority></url>\n"
                for pg in extra_pages(company)
            )
            + "</urlset>\n"
        ),
    }


def _disallowed(base) -> set[str]:
    """Paths an existing robots.txt keeps out, so the sitemap can agree with it."""
    path = Path(base) / "robots.txt"
    if not path.is_file():
        return set()
    out = set()
    try:
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            key, _, value = line.partition(":")
            if key.strip().lower() == "disallow" and value.strip() not in ("", "/"):
                out.add(value.strip().lstrip("/"))
    except OSError:
        return set()
    return out


def _robots_with_sitemap(base, url: str) -> str:
    """The site's own robots.txt with its `Sitemap:` line corrected, or a new one.

    Only that line. Regenerating the file would have deleted a real decision: the
    owner's robots.txt allows GPTBot, ClaudeBot, PerplexityBot and Google-Extended,
    with a comment explaining why. Overwriting that to fix a hostname would be the
    product throwing away the operator's SEO policy.
    """
    path = Path(base) / "robots.txt"
    line = f"Sitemap: {url}/sitemap.xml"
    fresh = "User-agent: *\nAllow: /\n\n" + line + "\n"
    if not path.is_file():
        return fresh
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return fresh
    kept = [ln for ln in text.splitlines() if not ln.strip().lower().startswith("sitemap:")]
    while kept and not kept[-1].strip():
        kept.pop()
    return "\n".join([*kept, "", line, ""])


def companions_for_folder(site_dir, url: str) -> dict[str, str]:
    """robots.txt and sitemap.xml for a site the company owns, from its real files.

    `companions` above builds them from `company.yaml`'s pages, which is right for a
    generated site and wrong for one with its own: the pages on disk are the pages
    that exist. Empty when there is no absolute address, for the same reason
    `companions` is — a sitemap listing a host nobody owns tells a crawler to index
    somebody else.
    """
    base = Path(site_dir)
    url = str(url or "").rstrip("/")
    if not url or not base.is_dir():
        return {}
    # A page the site itself keeps out of the index has no business in its sitemap.
    # Measured: `merci.html` is noindex and disallowed in robots.txt, and the first
    # version of this listed it anyway — a sitemap that contradicts the robots.txt
    # beside it is a defect a crawler reports back.
    blocked = _disallowed(base)
    pages = []
    for path in sorted(base.rglob("*.html")):
        rel = path.relative_to(base).as_posix()
        head = path.read_text(encoding="utf-8", errors="replace")[:2000]
        if rel in blocked or "noindex" in head:
            continue
        if rel == "index.html":
            pages.append(("", "1.0"))
        elif rel.endswith("/index.html"):
            pages.append((rel[: -len("index.html")], "0.6"))
        else:
            pages.append((rel, "0.8"))
    if not pages:
        return {}
    entries = "".join(
        f"  <url><loc>{_esc(url)}/{loc}</loc><changefreq>monthly</changefreq>"
        f"<priority>{pri}</priority></url>\n"
        for loc, pri in pages
    )
    return {
        "robots.txt": _robots_with_sitemap(base, url),
        "sitemap.xml": (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
            + entries
            + "</urlset>\n"
        ),
    }


def point_absolute_tags(site_dir, url: str) -> int:
    """Make every canonical in an owned site name `url`, adding one where there is
    none. Returns how many tags were written.

    A host swap where a tag exists, an insertion where it does not. Both are needed:
    Vigil's six canonical tags all named a domain the operator does not own, so they
    were removed — right, by the rule that an absolute tag is omitted rather than
    pointed at a guess — and a function that only rewrites would have left those pages
    with no canonical at all once an address finally existed.

    Prose is never touched. A canonical link is generated infrastructure; the sentence
    next to it is the operator's, and a domain named in a paragraph stays as written.
    """
    base = Path(site_dir)
    url = str(url or "").rstrip("/")
    if not url or not base.is_dir():
        return 0
    # Up to and including the opening quote, then the scheme and host only — the path
    # after it is kept, because `/tech.html` has to stay `/tech.html`.
    host = re.compile(r'((?:rel="canonical"\s+href|property="og:url"\s+content)=")https?://[^/"]*')
    changed = 0
    for path in sorted(base.rglob("*.html")):
        text = path.read_text(encoding="utf-8", errors="replace")
        fixed, n = host.subn(lambda m: m.group(1) + url, text)
        if 'rel="canonical"' not in fixed:
            rel = path.relative_to(base).as_posix()
            loc = (
                ""
                if rel == "index.html"
                else rel[: -len("index.html")]
                if rel.endswith("/index.html")
                else rel
            )
            tag = f'<link rel="canonical" href="{_esc(url)}/{loc}">'
            if "</head>" in fixed:
                fixed = fixed.replace("</head>", f"{tag}\n</head>", 1)
                n += 1
            # No </head> means a fragment rather than a page; nothing is inserted
            # blindly into markup whose shape is unknown.
        if n:
            path.write_text(fixed, encoding="utf-8")
            changed += n
    return changed


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


def faq_html_from(pairs: list[tuple[str, str]], txt: dict[str, str]) -> str:
    """The rendered section, from questions already asked.

    Split out from `faq_html` because the answers now feed two places — the
    visible section and the FAQPage structured data — and asking a model the
    same questions twice to build one page would be paying twice for one answer.
    """
    if not pairs:
        return ""
    items = "".join(
        f"<details><summary>{_esc(q)}</summary><p>{_esc(a)}</p></details>" for q, a in pairs
    )
    return f'<section id="faq"><h2>{_esc(txt["faq"])}</h2><div class="faq">{items}</div></section>'


def faq_html(company: dict, store) -> str:
    """Kept for callers that want the fragment on its own."""
    return faq_html_from(faq_pairs(company, store), strings(company.get("language", "en")))


# --------------------------------------------------------------------------
# The blocks that persuade, none of them invented
# --------------------------------------------------------------------------


def _steps_html(company: dict, txt: dict) -> str:
    """`site.how_it_works`: the protocol, numbered.

    Numbering here is not decoration — these are sequential and the order is
    the information. A check-in that happens after the analysis is a different
    product.
    """
    steps = [s for s in (company.get("site") or {}).get("how_it_works") or [] if str(s).strip()]
    if not steps:
        return ""
    items = "".join(
        f'<li><span class="step-n">{i}</span><span>{_esc(step)}</span></li>'
        for i, step in enumerate(steps, 1)
    )
    return f'<section id="how"><h2>{_esc(txt["how"])}</h2><ol class="how">{items}</ol></section>'


def _proof_html(company: dict, txt: dict) -> str:
    """`site.proof`: claims that carry a source, and only those.

    A claim without a source is the machine-readable form of the invented
    testimonial — it looks like evidence and is not. Entries are `text` plus
    `source`; an entry missing either is dropped, and dropped loudly enough to
    find in the log rather than silently.
    """
    raw = (company.get("site") or {}).get("proof") or []
    kept = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        text, source = str(item.get("text", "")).strip(), str(item.get("source", "")).strip()
        if text and source:
            kept.append((text, source))
        elif text:
            log.warning("site: proof %r has no source, so it is not published", text[:60])
    if not kept:
        return ""
    items = "".join(
        f'<li><span class="claim">{_esc(text)}</span>'
        f'<span class="source">{_esc(source)}</span></li>'
        for text, source in kept
    )
    return (
        f'<section id="proof"><h2>{_esc(txt["proof"])}</h2><ul class="proof">{items}</ul></section>'
    )


def _voices_html(company: dict, txt: dict) -> str:
    """`site.testimonials`: quotes with a name against them.

    An unattributed quote on a commercial page is a fabrication with quotation
    marks around it. This generator has already been caught printing terms of
    sale nobody agreed to; a testimonial is the same fault with a face on it.
    Entries need `quote` and `who`, or they do not appear.
    """
    raw = (company.get("site") or {}).get("testimonials") or []
    kept = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        quote, who = str(item.get("quote", "")).strip(), str(item.get("who", "")).strip()
        if quote and who:
            kept.append((quote, who))
        elif quote:
            log.warning("site: a testimonial has no attribution, so it is not published")
    if not kept:
        return ""
    items = "".join(
        f"<figure><blockquote>{_esc(q)}</blockquote><figcaption>{_esc(w)}</figcaption></figure>"
        for q, w in kept
    )
    return (
        f'<section id="voices"><h2>{_esc(txt["voices"])}</h2>'
        f'<div class="voices">{items}</div></section>'
    )


def _privacy_html(company: dict, txt: dict) -> str:
    """`site.privacy`: what happens to the visitor's data, in their words."""
    points = [p for p in (company.get("site") or {}).get("privacy") or [] if str(p).strip()]
    if not points:
        return ""
    items = "".join(f"<li>{_esc(p)}</li>" for p in points)
    return (
        f'<section id="privacy"><h2>{_esc(txt["privacy"])}</h2>'
        f'<ul class="gets">{items}</ul></section>'
    )


def extra_pages(company: dict) -> list[dict]:
    """`site.pages`: secondary pages, each a title and some prose.

    One page was the whole site. An operator with something to say about their
    architecture, their method or their terms had nowhere to put it, and the
    nav had nothing to point at.

        site:
          pages:
            - slug: tech
              title: Architecture
              body: |
                Two paragraphs about how it works.
    """
    out = []
    for page in (company.get("site") or {}).get("pages") or []:
        if not isinstance(page, dict):
            continue
        slug = text.slugify(page.get("slug", ""))
        title = str(page.get("title", "")).strip()
        body = str(page.get("body", "")).strip()
        if slug and title and body:
            out.append({"slug": slug, "title": title, "body": body})
        elif slug or title:
            log.warning("site: page %r needs a slug, a title and a body; skipped", slug or title)
    return out


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
    # Ordered the way somebody decides: what it is, how it works, what it rests
    # on, who vouches for it, what happens to their data — then the price. The
    # operator's own previous site had ten sections in roughly this order, and
    # they said plainly it was better than the single page this produced.
    parts.append(_steps_html(company, txt))
    parts.append(_proof_html(company, txt))
    parts.append(_voices_html(company, txt))
    parts.append(_privacy_html(company, txt))

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
    # Asked once, used twice: rendered on the page and again as FAQPage
    # structured data, which is what earns the questions a rich result.
    faq_qa = faq_pairs(company, store)
    faq = faq_html_from(faq_qa, txt)
    if faq:
        faq = f'<div class="band"><div class="wrap">{faq}</div></div>'

    # The <title> is what a search result shows, so it leads with the promise
    # rather than the company name — a reader scanning ten results has no idea
    # yet what "Vigil" is. Kept under the ~60 characters Google renders.
    # One nav shared by every page, so a visitor who lands on a sub-page can get
    # back. Relative links throughout: the site is a folder that has to open
    # from disk, with no server and no base href.
    pages = extra_pages(company)
    nav = f'<a class="nav" href="#pricing">{_esc(txt["pricing"])}</a>' + "".join(
        f'<a class="nav" href="{pg["slug"]}.html">{_esc(pg["title"])}</a>' for pg in pages
    )

    title = head if len(head) <= 58 else name
    if len(f"{title} · {name}") <= 60 and title != name:
        title = f"{title} · {name}"
    # Not the visual lede. The lede is a strapline sized for a hero; the meta
    # description is the two lines under a search result, and a 16-character one
    # wastes the only sentence a stranger will read before deciding. So it takes
    # the fullest text the config has and gives it the ~155 characters Google
    # renders, rather than whatever the layout happened to want.
    description = _opening(max((one_liner, product, head, lede), key=len) or head, limit=155)

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
<title>{_esc(title)}</title>
{head_tags(company, title, description, faq_qa)}
<style>{
        css(
            site.get("theme", "light"),
            site.get("font", "serif"),
            site.get("accent", DEFAULT_ACCENT),
        )
    }</style>
</head>
<body>
<header class="topbar">
  <div class="wrap">
    <div class="logo">{_esc(name)}</div>
    {nav}
  </div>
</header>
<main>
  <div class="band band-hero">
    <div class="wrap">
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
    </div>
  </div>
</main>
<footer>
  <div class="wrap">{_esc(name)} · {_esc(txt["built"])}</div>
</footer>
</body>
</html>"""

    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "index.html")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(doc)
    # robots.txt and sitemap.xml go beside the page so that whatever uploads the
    # directory uploads them too — every deploy provider in deploy.py ships the
    # folder, not a file list, so this needs no change anywhere else.
    for page in pages:
        paragraphs = "".join(
            f"<p>{_esc(para.strip())}</p>"
            for para in re.split(r"\n\s*\n", page["body"])
            if para.strip()
        )
        head_band = (
            '<div class="band band-hero"><div class="wrap"><div class="hero">'
            f"<h1>{_esc(page['title'])}</h1></div></div></div>"
        )
        sub = doc.replace(
            f"<title>{_esc(title)}</title>",
            f"<title>{_esc(page['title'])} · {_esc(name)}</title>",
        )
        start, end = sub.index("<main>"), sub.index("</main>") + len("</main>")
        sub = (
            sub[:start]
            + "<main>"
            + head_band
            + '<div class="band"><div class="wrap"><section class="story">'
            + paragraphs
            + "</section></div></div></main>"
            + sub[end:]
        )
        # On a sub-page the anchors have to return to the index, and this page
        # must not link to itself.
        sub = sub.replace('href="#pricing"', 'href="index.html#pricing"')
        sub = sub.replace(f'href="{page["slug"]}.html"', 'href="#"')
        with open(os.path.join(out_dir, f"{page['slug']}.html"), "w", encoding="utf-8") as fh:
            fh.write(sub)

    for filename, content in companions(company).items():
        with open(os.path.join(out_dir, filename), "w", encoding="utf-8") as fh:
            fh.write(content)
    return path
