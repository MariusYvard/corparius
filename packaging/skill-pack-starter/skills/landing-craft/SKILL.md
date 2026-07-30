---
name: landing-craft
description: What to write on a sales page, and what a generator must never write on one. Read before drafting a headline or a design brief for the company site.
allowed-tools: build_sales_site, draft_design_brief
source: adapted from the owner's NullToHero plugin, skills/siteasy
licence: Apache-2.0
---

## Never publish yourself thinking

A page shipped from this repo with this as its H1, at 4rem, on a live site:

> "Check-in, anonyme, en 90 secondes." Alternatively, a more punchy version:
> "Mental Check-in en 90s"

Write the line. Do not write about the line. No `Alternatively`, no `Here is a
headline:`, no `Option 1 / Option 2`, no wrapping quotation marks, no two
variants separated by a colon for the operator to choose between. If you have
two candidates, pick one — choosing is the work.

`sitegen.clean_headline` refuses all of these and falls back to the company's
own one-liner, so a page will not carry your deliberation. It will carry a
weaker headline instead, which is the cost of not deciding.

## Never write a claim the company did not make

The generator used to print "Cancel anytime" and "Instant onboarding" in the
pricing box of every page. Nobody had agreed to either. Those are terms of sale,
and inventing them on someone's commercial site is not a design shortcut, it is
a liability with their name on it.

Everything on the page comes from `company.yaml`: the price, the segment, the
pains, `offer.includes`. If a section has no real content, it does not appear —
an empty section is better than a filled template. Never invent a testimonial, a
customer count, a logo, a percentage, or a guarantee.

## Flat is not restrained, it is unfinished

The second failure, after the template was removed:

> "le site manque cruellement d'âme, on dirait une page blanche avec du texte"

Restraint without intent reads as mediocre, not refined. AI-generated landing
pages have flooded the internet and average is no longer findable, so a page
needs a point of view. Commit somewhere:

- **Change ground.** A page that is one colour top to bottom reads as a
  document. The generator uses three bands — a washed hero, plain sections, an
  inverted pricing block — and each change lands on a section boundary.
- **One number is the loudest thing on the page.** Usually the price. A sales
  page that sets its price at body weight has hidden its own argument.
- **Spend the boldness once.** One saturated accent, used on the hero ground,
  the button, the rules above headings, and nothing else. Keep everything
  around it quiet.
- **Never centre everything.** A centred hero over a grid of icon-title-subtitle
  cards is the shape every template has. When all of it is in the middle, none
  of it is anywhere.

## The type carries the page

Modular scale, ratio ≥ 1.25 — a flat scale reads as uncommitted. Headline large
enough to be the first thing, `text-wrap: balance`, running text near 62
characters. Light type on a dark ground gets more line-height, because it reads
lighter than it is.

Weight and size have to carry the hierarchy on their own: turn the colour off
and the page should still have a shape.

## Write for the language the company speaks

`company.yaml` has a `language` field. Section headings, the button and the
billing note follow it. Do not draft English copy for a French company because
English is what you reached for first.

Translations are longer: German +30%, French +20%. Nothing that holds text gets
a fixed width.

## The button says what it does

A button that opens Stripe and a button that scrolls to a price are not the same
button and must not carry the same word. Never `OK`, `Submit`, `Click here`.
Verb, and what happens.

## What the page must not need

One file. No script, no webfont, no CDN, no external image, no build step. It
has to open from a folder, on a plane, forever. A design that reaches for a
font URL has traded the only property this page is guaranteed to have.

The graphic that gives the page presence is generated: a band of bars whose
heights come from a hash of the company name, so every company gets a different
one and every rebuild gives the same one. Distinctiveness with zero assets.
