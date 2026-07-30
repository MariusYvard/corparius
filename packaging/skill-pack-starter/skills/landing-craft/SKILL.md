---
name: landing-craft
description: What to write on a sales page, and what a generator must never write on one. Read before drafting a headline or a design brief for the company site.
allowed-tools: build_sales_site, draft_design_brief
source: adapted from the owner's NullToHero plugin, skills/siteasy
licence: Apache-2.0
---

Every rule here is one this generator already broke on a live page.

## Never publish yourself thinking

A page shipped with this H1, at 4rem: `"Check-in, anonyme, en 90 secondes."
Alternatively, a more punchy version: "Mental Check-in en 90s"`.

Write the line; do not write *about* the line. No `Alternatively`, no `Here is a
headline:`, no `Option 1 / Option 2`, no wrapping quotes, no two variants for
someone else to choose between. If you have two candidates, pick one — choosing
is the work.

## Never claim what the company did not

Every page printed "Cancel anytime" and "Instant onboarding". Nobody had agreed
to either, on somebody else's commercial site. Everything comes from
`company.yaml`. A section with nothing real in it is omitted, never templated.
No invented testimonial, customer count, percentage or guarantee.

This holds double for structured data, where a lie is invisible on screen and
still shows in the search result: never `aggregateRating`, `reviewCount` or a
`Review`. No price means no `Offer` — not `"price": "0"`, which advertises a
free product.

## Flat is not restrained, it is unfinished

Second failure, after the template came out: *"on dirait une page blanche avec du
texte"*. Restraint without intent reads as mediocre. Commit somewhere:

- **Change ground.** One colour top to bottom reads as a document.
- **One number is the loudest thing on the page.** Usually the price.
- **Spend the boldness once**, then keep everything around it quiet.
- **Never centre everything.** A centred hero over a grid of
  icon-title-subtitle cards is the shape every template has.

## Contrast is a number, not an impression

The dark pricing band shipped at **1.16:1**. WCAG AA is 4.5:1 for body text,
3.0:1 for large text and controls. Measure; never assume a colour that works on
one ground works on another. Two traps that both shipped:

- **`#fff` is not a button label.** 1.74:1 on a mid green. The label is
  whichever of white and near-black wins against the chosen accent.
- **A value that resolves in the browser cannot be checked.** No `color-mix`, no
  alpha on text — their own reference calls alpha a design smell for this
  reason. Resolve colours before writing them.

Decoration is exempt: the signature band is `aria-hidden`.

## Findable

`<title>` leads with the promise, not the company name — a reader scanning ten
results does not know yet what the company is. Under ~60 characters, description
under ~155, one H1, `header`/`main`/`footer` as real landmarks.

## Type, language, buttons

Modular scale, ratio ≥ 1.25; a flat scale reads as uncommitted. Weight and size
carry the hierarchy — turn the colour off and the page should still have shape.
Light type on dark gets more line-height.

Write in `company.language`, never in whatever you reached for first.
Translations run longer (German +30%, French +20%), so nothing holding text gets
a fixed width.

A button that opens Stripe and a button that scrolls to a price are not the same
button. Never `OK`, `Submit`, `Click here`. Verb, and what happens.

## What the page must never need

One file. No script, no webfont, no CDN, no external image, no build step — it
opens from a folder, on a plane, forever. A font URL trades away the only
property this page is guaranteed to have. The graphic that gives it presence is
generated from a hash of the company name: different per company, identical
across rebuilds, zero assets.
