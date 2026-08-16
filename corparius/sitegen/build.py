"""One landing page, assembled. Rank 4.

The entry point, and the only name outside this package needs: `sitegen.build_site`. Everything
above it is a part this function puts together — palette, stylesheet, copy, head, sections — and
the order it does that in is the file's whole content.
"""

from __future__ import annotations

import logging
import os
import re

from .. import housestyle, readiness
from ..config import cfg
from .base import esc, norm
from .companions import companions
from .copy import clean_headline, opening, strings
from .head import head_tags
from .palette import DEFAULT_ACCENT, signature
from .sections import (
    extra_pages,
    faq_html_from,
    faq_pairs,
    legal_html,
    privacy_html,
    programs_html,
    proof_html,
    steps_html,
    voices_html,
)
from .style import css

log = logging.getLogger("corparius.sitegen.build")


def _styled(company: dict, headline: str | None):
    """The company's text fields through its charter. Returns (company, headline, what is left).

    A copy, never the caller's dict: `build_site` is handed the live company config by the
    orchestrator and by the console, and quietly editing it would make a page build change what the
    next agent turn reads.

    Only the fields that become page text. `slug`, `payment_link` and the rest are identifiers and
    URLs, and running an editorial rule over a URL is how a checker earns its way into being turned
    off.
    """
    style = housestyle.load(str(company.get("slug") or ""))
    left: list[dict] = []

    def walk(value):
        if isinstance(value, str):
            fixed, hits = housestyle.apply(value, style)
            left.extend(hits)
            return fixed
        if isinstance(value, list):
            return [walk(item) for item in value]
        return value

    out = dict(company)
    for key in ("name", "one_liner"):
        if isinstance(out.get(key), str):
            out[key] = walk(out[key])
    offer = dict(out.get("offer") or {})
    for key in ("product", "description", "pitch", "includes"):
        if key in offer:
            offer[key] = walk(offer[key])
    out["offer"] = offer
    icp = dict(out.get("icp") or {})
    for key in ("segment", "pains"):
        if key in icp:
            icp[key] = walk(icp[key])
    out["icp"] = icp
    return out, (walk(headline) if isinstance(headline, str) else headline), left


def build_site(company: dict, out_dir: str, headline: str | None = None, store=None) -> str:
    """Render a single-file sales page for `company` into out_dir/index.html.

    `store` is only needed for the generated FAQ (see `faq_pairs`); without it
    the page is exactly what it was before, which is what every caller that has
    no store should get.
    """
    # **The company's own words, through its charter, before anything derives from them.**
    #
    # The page has two sources of prose and only one of them was ever checked. A drafted headline
    # passes the executor's styling on its way out of the model; `company.yaml` does not pass
    # anything, and its text is most of what a visitor reads. Curly quotation marks are straightened
    # (a word processor puts them there and nobody chose them); everything else is reported and left
    # exactly as written, because an operator's own sentence is theirs and a charter is an
    # instruction to their agents rather than a licence to rewrite them.
    #
    # Here rather than at each use: `head`, `lede`, `story`, the pains and the includes are all
    # slices of these fields, and fixing a slice leaves the original wrong.
    company, headline, unfixed = _styled(company, headline)
    if unfixed:
        log.info(
            "site: %d style violation(s) in this company's own copy: %s",
            len(unfixed),
            ", ".join(sorted({v["rule"] for v in unfixed})),
        )

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
    lede = opening(one_liner if norm(one_liner) != norm(head) else product)
    if norm(lede) == norm(head):
        lede = ""
    # Whatever the lede could not carry, in full, in its own paragraph. Real
    # content the previous version simply never rendered.
    story = product if len(product) > len(lede) and norm(product) != norm(lede) else ""

    cta_label = txt["cta_buy"] if pay else txt["cta_talk"]
    cta_href = pay or "#pricing"
    cta = f'<a class="btn" href="{esc(cta_href)}">{esc(cta_label)}</a>'

    price_txt = f"{esc(price)} EUR" if price is not None else esc(txt["talk"])
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
    # **How you pay, when there is nothing to click.** A company paid by transfer against an invoice
    # had a page whose only call to action was "talk to us" and which said nothing at all about the
    # transaction: a visitor could not tell whether that meant a demo, a quote or a shop that was
    # broken. This is the same kind of chip as the Stripe one, on the other route.
    #
    # Only when there is no link, and never both. Two payment claims on one page is a page that has
    # not decided how it sells, and the checkout is the stronger offer wherever it exists.
    elif not pay and readiness.invoiced():
        facts.append(txt["invoice"])
    facts_html = (
        '<div class="facts">' + "".join(f"<span>{esc(f)}</span>" for f in facts) + "</div>"
        if facts
        else ""
    )
    # ...and it is not thrown away either. Who a product is for is real content;
    # it just belongs in a sentence rather than in a chip.
    who = segment if segment and len(segment) > 64 else ""
    who_html = f'<p class="who">{esc(txt["for"].format(segment=who))}</p>' if who else ""

    # A section with nothing real in it is left out entirely rather than filled
    # with a template. That is why these are appended conditionally and joined
    # at the end: an empty "Why it works" used to render three cards of
    # corparius's own marketing copy on somebody else's page.
    parts = []
    if story:
        parts.append(f'<section class="story"><p>{esc(story)}</p></section>')
    if who_html:
        parts.append(f'<section class="who-sec">{who_html}</section>')
    if pains:
        items = "".join(f"<li>{esc(p)}</li>" for p in pains)
        parts.append(
            f'<section><h2>{esc(txt["problem"])}</h2><ul class="pains">{items}</ul></section>'
        )
    if includes:
        items = "".join(f"<li>{esc(i)}</li>" for i in includes)
        parts.append(
            f'<section><h2>{esc(txt["includes"])}</h2><ul class="gets">{items}</ul></section>'
        )
    # Ordered the way somebody decides: what it is, how it works, what it rests
    # on, who vouches for it, what happens to their data — then the price. The
    # operator's own previous site had ten sections in roughly this order, and
    # they said plainly it was better than the single page this produced.
    parts.append(steps_html(company, txt))
    parts.append(proof_html(company, txt))
    parts.append(voices_html(company, txt))
    # Before privacy: a visitor who just used the thing is the one who then asks what
    # happens to what they typed.
    parts.append(programs_html(company, txt))
    parts.append(privacy_html(company, txt))
    # Last before the footer, which is where a reader looks for it and where every site that
    # carries one puts it.
    parts.append(legal_html(company, txt))

    body_html = "".join(p for p in parts if p)
    if body_html:
        body_html = f'<div class="band"><div class="wrap">{body_html}</div></div>'

    # The price gets the one band that inverts. It is the number the whole page
    # is arguing towards, and the previous version set it at 2.4rem inside a
    # grey box, which is where you put a number you would rather not mention.
    pricing = (
        f'<div class="band band-dark"><div class="wrap">'
        f'<section id="pricing"><h2>{esc(txt["pricing"])}</h2>'
        f'<div class="price"><div><div class="amt">{price_txt}</div>'
        f'<div class="per">{esc(billing or txt["oneoff"])}</div></div>{cta}</div>'
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
    nav = f'<a class="nav" href="#pricing">{esc(txt["pricing"])}</a>' + "".join(
        f'<a class="nav" href="{pg["slug"]}.html">{esc(pg["title"])}</a>' for pg in pages
    )

    title = head if len(head) <= 58 else name
    if len(f"{title} · {name}") <= 60 and title != name:
        title = f"{title} · {name}"
    # Not the visual lede. The lede is a strapline sized for a hero; the meta
    # description is the two lines under a search result, and a 16-character one
    # wastes the only sentence a stranger will read before deciding. So it takes
    # the fullest text the config has and gives it the ~155 characters Google
    # renders, rather than whatever the layout happened to want.
    description = opening(max((one_liner, product, head, lede), key=len) or head, limit=155)

    # The closing block repeats the CTA, not the H1. A page that ends by saying
    # its own headline again word for word has stopped making an argument — but
    # a closing heading is a heading, so anything long goes back to the H1
    # rather than setting a paragraph at 3rem.
    closer = lede if lede and norm(lede) != norm(head) and len(lede) <= 90 else head

    doc = f"""<!doctype html>
<html lang="{esc(language)}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)}</title>
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
    <div class="logo">{esc(name)}</div>
    {nav}
  </div>
</header>
<main>
  <div class="band band-hero">
    <div class="wrap">
      <div class="hero">
        <h1>{esc(head)}</h1>
        {f'<p class="lede">{esc(lede)}</p>' if lede else ""}
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
        <h2>{esc(closer)}</h2>
        {cta}
      </div>
    </div>
  </div>
</main>
<footer>
  <div class="wrap">{esc(name)} · {esc(txt["built"])}</div>
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
            f"<p>{esc(para.strip())}</p>"
            for para in re.split(r"\n\s*\n", page["body"])
            if para.strip()
        )
        head_band = (
            '<div class="band band-hero"><div class="wrap"><div class="hero">'
            f"<h1>{esc(page['title'])}</h1></div></div></div>"
        )
        sub = doc.replace(
            f"<title>{esc(title)}</title>",
            f"<title>{esc(page['title'])} · {esc(name)}</title>",
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
