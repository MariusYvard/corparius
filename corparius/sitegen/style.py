"""The stylesheet, emitted from a palette. Rank 4.

One function, and it stays one: the CSS is a single template because the page is a single
self-contained file with no build step and no external asset. Splitting it by section would
mean six templates that have to agree about the same custom properties.

Stage 9 rebuilds the *console*, not this. A generated sales page has no framework and wants
none — it is read by a stranger on a phone with one round trip.
"""

from __future__ import annotations

import logging

from .palette import DEFAULT_ACCENT, SANS, SERIF, palette_for

log = logging.getLogger("corparius.sitegen.style")


def css(theme: str = "light", font: str = "serif", accent: str = DEFAULT_ACCENT) -> str:
    palette = palette_for(theme, accent)
    display = SERIF if font == "serif" else SANS
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
  --display:{display};--body:{SANS};
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

/* The company's own programs. The only interactive part of a page that is
   otherwise a static file, so it is the one place a visitor types — and it
   shipped with no rules at all, which means a browser's default input and
   button under a section whose every neighbour is designed. Flat is how a
   generated page reads as unfinished. */
.programs{{display:grid;gap:22px;grid-template-columns:repeat(auto-fit,minmax(300px,1fr))}}
.program{{padding:24px;border:1px solid var(--line);border-radius:10px;
  display:grid;gap:14px;align-content:start}}
.program h3{{font-family:var(--display);font-size:var(--f1);margin:0;
  line-height:1.2}}
.program p{{margin:0;color:var(--muted);font-size:.95rem;line-height:1.45}}
.program form{{display:flex;gap:10px;flex-wrap:wrap}}
.program input{{flex:1 1 12ch;min-width:0;padding:12px 14px;font:inherit;
  font-size:.95rem;color:var(--fg);background:transparent;
  border:1px solid var(--line);border-radius:8px}}
.program input:focus-visible{{outline:2px solid var(--accent);outline-offset:2px}}
.program button{{padding:12px 20px;font:inherit;font-size:.95rem;font-weight:600;
  cursor:pointer;color:var(--on-accent);background:var(--accent);border:0;
  border-radius:8px}}
.program button:hover{{filter:brightness(1.07)}}
/* `white-space:pre-wrap` because a program's answer is text it formatted, and
   a long line must wrap rather than widen the card past its column. */
.program-out{{margin:0;padding:16px;white-space:pre-wrap;overflow-wrap:anywhere;
  font:inherit;font-size:.92rem;line-height:1.45;color:var(--fg);
  background:var(--tint);border-radius:8px}}
.program-off{{margin:0;color:var(--muted);font-size:.85rem}}

.close{{padding:var(--gap) 0 calc(var(--gap) * .7)}}
.close h2{{font-size:clamp(2rem,5vw,3.2rem);margin-bottom:34px;max-width:18ch;
  border:0;padding-top:0}}
footer .wrap{{padding-bottom:60px;color:var(--muted);font-size:.88rem;
  display:flex;gap:10px;align-items:center}}
footer .wrap::before{{content:"";width:22px;height:2px;background:var(--accent);
  flex:none}}

@media(prefers-reduced-motion:reduce){{*{{transition:none!important}}}}
"""
