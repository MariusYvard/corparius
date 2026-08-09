"""What the page says, and the two things the generator refuses to write. Rank 4.

Both rules were broken by a page that actually shipped, which is why they are here rather than
in a style guide:

**It never publishes the model thinking out loud.** A real page went out with
`"Check-in, anonyme, en 90 secondes." Alternatively, a more punchy version: "Mental Check-in en
90s"` as its H1. `clean_headline` is the gate, and what it refuses falls back to the value
proposition in the config — which a human wrote.

**It never writes a claim the company did not make.** An earlier version printed "Cancel
anytime" and "Instant onboarding" in every pricing box it produced. Nobody had said either was
true. Terms of sale are not filler, so `offer.includes` is read from the config or the list is
simply absent.
"""

from __future__ import annotations

import logging
import re

log = logging.getLogger("corparius.sitegen.copy")


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


def opening(text: str, limit: int = 190) -> str:
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
