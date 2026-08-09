"""`<head>`: the tags a stranger never sees and a crawler reads first. Rank 4.

Title, description, canonical, Open Graph, JSON-LD. `point_absolute_tags` is the one with a
measured history: a page is generated with relative URLs so it can be previewed from disk, and
the absolute forms are stamped in only once a real address is known — which is at publish time,
not at build time, because before the first deploy nobody knows what the address will be.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from .base import esc

log = logging.getLogger("corparius.sitegen.head")


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
        f'<meta name="description" content="{esc(description)}">',
        '<meta name="robots" content="index,follow,max-image-preview:large">',
        f'<meta property="og:type" content="{"product" if price is not None else "website"}">',
        f'<meta property="og:site_name" content="{esc(name)}">',
        f'<meta property="og:title" content="{esc(title)}">',
        f'<meta property="og:description" content="{esc(description)}">',
        f'<meta property="og:locale" content="{esc(language.replace("-", "_"))}">',
        '<meta name="twitter:card" content="summary_large_image">',
        f'<meta name="twitter:title" content="{esc(title)}">',
        f'<meta name="twitter:description" content="{esc(description)}">',
    ]
    if url:
        tags.insert(0, f'<link rel="canonical" href="{esc(url)}/">')
        tags.append(f'<meta property="og:url" content="{esc(url)}/">')

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
            tag = f'<link rel="canonical" href="{esc(url)}/{loc}">'
            if "</head>" in fixed:
                fixed = fixed.replace("</head>", f"{tag}\n</head>", 1)
                n += 1
            # No </head> means a fragment rather than a page; nothing is inserted
            # blindly into markup whose shape is unknown.
        if n:
            path.write_text(fixed, encoding="utf-8")
            changed += n
    return changed
