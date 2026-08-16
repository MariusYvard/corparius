"""The optional blocks: FAQ, steps, proof, voices, privacy, extra pages. Rank 4.

Each one is absent unless the config supplies it, and that is the same rule as the pricing box:
a section with invented content is worse than no section. `faq_pairs` is the only one that reads
like logic rather than assembly — it takes what an agent wrote and refuses what is not a pair.
"""

from __future__ import annotations

import logging

from ..kernel import text
from .base import esc

log = logging.getLogger("corparius.sitegen.sections")


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
    from .. import apps as apps_mod

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

    Takes the pairs rather than fetching them, because the answers feed two places (the visible
    section and the FAQPage structured data) and asking a model the same questions twice to build
    one page would be paying twice for one answer.
    """
    if not pairs:
        return ""
    items = "".join(
        f"<details><summary>{esc(q)}</summary><p>{esc(a)}</p></details>" for q, a in pairs
    )
    return f'<section id="faq"><h2>{esc(txt["faq"])}</h2><div class="faq">{items}</div></section>'


def steps_html(company: dict, txt: dict) -> str:
    """`site.how_it_works`: the protocol, numbered.

    Numbering here is not decoration — these are sequential and the order is
    the information. A check-in that happens after the analysis is a different
    product.
    """
    steps = [s for s in (company.get("site") or {}).get("how_it_works") or [] if str(s).strip()]
    if not steps:
        return ""
    items = "".join(
        f'<li><span class="step-n">{i}</span><span>{esc(step)}</span></li>'
        for i, step in enumerate(steps, 1)
    )
    return f'<section id="how"><h2>{esc(txt["how"])}</h2><ol class="how">{items}</ol></section>'


def proof_html(company: dict, txt: dict) -> str:
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
        f'<li><span class="claim">{esc(text)}</span><span class="source">{esc(source)}</span></li>'
        for text, source in kept
    )
    return (
        f'<section id="proof"><h2>{esc(txt["proof"])}</h2><ul class="proof">{items}</ul></section>'
    )


def voices_html(company: dict, txt: dict) -> str:
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
        f"<figure><blockquote>{esc(q)}</blockquote><figcaption>{esc(w)}</figcaption></figure>"
        for q, w in kept
    )
    return (
        f'<section id="voices"><h2>{esc(txt["voices"])}</h2>'
        f'<div class="voices">{items}</div></section>'
    )


def privacy_html(company: dict, txt: dict) -> str:
    """`site.privacy`: what happens to the visitor's data, in their words."""
    points = [p for p in (company.get("site") or {}).get("privacy") or [] if str(p).strip()]
    if not points:
        return ""
    items = "".join(f"<li>{esc(p)}</li>" for p in points)
    return (
        f'<section id="privacy"><h2>{esc(txt["privacy"])}</h2>'
        f'<ul class="gets">{items}</ul></section>'
    )


# What French law names, in the order a reader looks for it. `LCEN` article 6 III for a site that
# sells, plus the commercial register identifiers. Declared as data so the section renders whatever
# the operator filled and nothing else: a legal notice with `RCS: ` and a blank after it is worse
# than one that omits the line, because it says the company looked and found nothing.
#
# **This is the fields the law names, not legal advice**, and `docs/conformite-fr.md` is where the
# obligations themselves are written down.
LEGAL_FIELDS = (
    ("publisher", "Éditeur"),
    ("legal_form", "Forme juridique"),
    ("capital", "Capital social"),
    ("address", "Siège social"),
    ("email", "Contact"),
    ("phone", "Téléphone"),
    ("registration", "RCS / SIREN"),
    ("vat", "TVA intracommunautaire"),
    ("director", "Directeur de la publication"),
)


def apps_html(company: dict, txt: dict) -> str:
    """`site.apps`: the company's own programs, on its own page.

    **This is the one section that puts JavaScript on a generated page, and it is opt-in for that
    reason.** The generator's defended property is that the page is a single static file with nothing
    to reach and nothing left running — `faq_pairs` bakes its answers at build time and says why. A
    company that lists an app here has decided otherwise about its own site, for a program it wrote
    and that runs on its own machine.

    So: absent unless asked for, and honest about what it is when it is. The address is loopback,
    which means the demo works for the operator and for nobody else — a visitor on the internet gets
    the fallback line rather than a spinner that never resolves, because a form that fails silently
    is worse than a sentence saying it needs the app running.
    """
    from .. import codeapps

    wanted = [
        str(n).strip() for n in ((company.get("site") or {}).get("apps") or []) if str(n).strip()
    ]
    if not wanted:
        return ""
    slug = str(company.get("slug") or "")
    have = {app.name: app for app in codeapps.load(slug)}
    cards = []
    for name in wanted:
        app = have.get(text.slugify(name))
        if app is None:
            log.warning("site: %r is listed under site.apps and this company has no such app", name)
            continue
        cards.append(
            f'<article class="app" data-app="{esc(app.name)}" data-url="{esc(app.url)}">'
            f"<h3>{esc(app.name)}</h3>"
            + (f"<p>{esc(app.description)}</p>" if app.description else "")
            + f'<form><input name="q" placeholder="{esc(txt["appAsk"])}" autocomplete="off">'
            f'<button type="submit">{esc(txt["appSend"])}</button></form>'
            f'<pre class="app-out" hidden></pre>'
            f'<p class="app-off">{esc(txt["appOff"])}</p></article>'
        )
    if not cards:
        return ""
    return (
        f'<section id="apps"><h2>{esc(txt["apps"])}</h2>'
        f'<div class="apps">{"".join(cards)}</div>{APPS_SCRIPT}</section>'
    )


# Small, inline and dependency-free, for the same reason the rest of this generator is: a page that
# pulled a framework to send one request would be a page whose behaviour lives on somebody else's
# CDN. It hides the "not running" line only once an answer arrives, so the page is honest before
# JavaScript has run at all and honest again if the app is not there.
APPS_SCRIPT = """<script>
for (const card of document.querySelectorAll('.app')) {
  const out = card.querySelector('.app-out'), off = card.querySelector('.app-off');
  card.querySelector('form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const q = new FormData(e.target).get('q') || '';
    out.hidden = false; out.textContent = '...';
    try {
      const r = await fetch(card.dataset.url + '/?q=' + encodeURIComponent(q));
      out.textContent = await r.text();
      off.hidden = true;
    } catch (err) { out.hidden = true; off.hidden = false; }
  });
}
</script>"""


def legal_html(company: dict, txt: dict) -> str:
    """`legal:`: who publishes this site and where to reach them.

    Mirrors `privacy_html` deliberately, down to the empty return: a section nobody filled must not
    render an empty heading. A company that sells to French customers is required to carry this, and
    a page that carries the heading with nothing under it satisfies nobody.
    """
    legal = company.get("legal") or {}
    if not isinstance(legal, dict):
        return ""
    rows = [
        f"<li><strong>{esc(label)}</strong> {esc(str(legal[key]).strip())}</li>"
        for key, label in LEGAL_FIELDS
        if str(legal.get(key) or "").strip()
    ]
    host = str(legal.get("host") or "").strip()
    if host:
        rows.append(f"<li><strong>{esc(txt['host'])}</strong> {esc(host)}</li>")
    if not rows:
        return ""
    return (
        f'<section id="legal"><h2>{esc(txt["legal"])}</h2>'
        f'<ul class="gets">{"".join(rows)}</ul></section>'
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
