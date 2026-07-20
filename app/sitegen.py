"""Sales-site generator. One opinionated, conversion-focused landing page built
from a company config, as a single self-contained HTML file (inline CSS, no
build step, no external assets). Where NullToHero is a broad design-and-audit
toolkit, this is the straight-to-the-point path: config in, a sellable page out,
with a checkout CTA wired to a Stripe payment link.
"""

from __future__ import annotations

import html as _html
import os

from . import cfg

CSS = """
:root{--bg:#0b0f17;--panel:#121826;--fg:#e6e9ef;--muted:#9aa4b2;--brand:#5b8cff;--brand2:#7b5bff;--line:#1f2937;--radius:14px}
*{box-sizing:border-box}
body{margin:0;font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;background:var(--bg);color:var(--fg);line-height:1.6}
a{color:inherit;text-decoration:none}
.wrap{max-width:1040px;margin:0 auto;padding:0 20px}
header{display:flex;align-items:center;justify-content:space-between;padding:22px 0}
.logo{font-weight:700;font-size:20px}
.btn{display:inline-block;background:linear-gradient(135deg,var(--brand),var(--brand2));color:#fff;padding:12px 22px;border-radius:999px;font-weight:600;border:0;cursor:pointer}
.btn.sm{padding:9px 16px;font-size:14px}
.hero{text-align:center;padding:72px 0 44px}
.hero h1{font-size:clamp(32px,6vw,56px);line-height:1.1;margin:0 0 16px}
.hero p{font-size:20px;color:var(--muted);max-width:640px;margin:0 auto 28px}
.section{padding:44px 0}
.section h2{font-size:28px;margin:0 0 20px}
.grid{display:grid;gap:18px;grid-template-columns:repeat(auto-fit,minmax(220px,1fr))}
.card{background:var(--panel);border:1px solid var(--line);border-radius:var(--radius);padding:22px}
.card h3{margin:0 0 8px;font-size:18px}
.card p,.card li{margin:0;color:var(--muted)}
.problem ul{color:var(--muted);padding-left:20px}
.price{background:var(--panel);border:1px solid var(--line);border-radius:var(--radius);padding:34px;text-align:center;max-width:390px;margin:0 auto}
.price .amt{font-size:46px;font-weight:800}
.price .per{color:var(--muted)}
.price ul{list-style:none;padding:0;margin:18px 0;text-align:left}
.price li{padding:8px 0;border-bottom:1px solid var(--line);color:var(--muted)}
footer{padding:40px 0;color:var(--muted);text-align:center;border-top:1px solid var(--line);margin-top:40px}
@media(max-width:640px){header{flex-direction:column;gap:12px}}
"""


def _esc(value) -> str:
    return _html.escape(str(value))


def build_site(company: dict, out_dir: str, headline: str | None = None) -> str:
    """Render a single-file sales page for `company` into out_dir/index.html."""
    name = company.get("name", "Your product")
    offer = company.get("offer", {}) or {}
    icp = company.get("icp", {}) or {}
    tagline = " ".join(
        (
            company.get("one_liner") or offer.get("product") or "The fastest way to get it done."
        ).split()
    )
    head = headline or tagline
    product = offer.get("product", "")
    segment = icp.get("segment", "")
    price = offer.get("price_eur")
    billing = offer.get("billing", "")
    pains = icp.get("pains", []) or []
    pay = offer.get("payment_link") or cfg.get("CORP_STRIPE_PAYMENT_LINK", "") or "#pricing"

    price_txt = f"{_esc(price)} EUR" if price is not None else "Let's talk"
    subhead = product or (f"For {segment}." if segment else "Made to sell.")
    pains_html = "".join(f"<li>{_esc(p)}</li>" for p in pains) or "<li>Too much manual work.</li>"
    feats = [
        ("Live in minutes", "One prompt turns into a working offer with checkout."),
        (
            "Pay as you go",
            f"Simple pricing at {price_txt}."
            if price is not None
            else "Simple, transparent pricing.",
        ),
        (
            f"Built for {segment}" if segment else "Built for the job",
            "Focused on one outcome, done well.",
        ),
    ]
    feat_html = "".join(
        f'<div class="card"><h3>{_esc(t)}</h3><p>{_esc(d)}</p></div>' for t, d in feats
    )
    incl_html = "".join(
        f"<li>{_esc(i)}</li>"
        for i in [product or "Full access", "Cancel anytime", "Instant onboarding"]
    )
    cta = f'<a class="btn" href="{_esc(pay)}">Get {_esc(name)}</a>'

    doc = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_esc(name)} | {_esc(tagline)}</title>
<meta name="description" content="{_esc(subhead)}">
<style>{CSS}</style>
</head>
<body>
<div class="wrap">
  <header>
    <div class="logo">{_esc(name)}</div>
    <a class="btn sm" href="#pricing">Pricing</a>
  </header>
  <section class="hero">
    <h1>{_esc(head)}</h1>
    <p>{_esc(subhead)}</p>
    {cta}
  </section>
  <section class="section problem">
    <h2>The problem</h2>
    <ul>{pains_html}</ul>
  </section>
  <section class="section">
    <h2>Why it works</h2>
    <div class="grid">{feat_html}</div>
  </section>
  <section class="section" id="pricing">
    <h2>Pricing</h2>
    <div class="price">
      <div class="amt">{price_txt}</div>
      <div class="per">{_esc(billing) if billing else "one-off"}</div>
      <ul>{incl_html}</ul>
      {cta}
    </div>
  </section>
  <footer>{_esc(name)} · built with corparius</footer>
</div>
</body>
</html>"""

    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "index.html")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(doc)
    return path
