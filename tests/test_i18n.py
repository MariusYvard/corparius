"""The 526 strings, as data, and the collision class that shipped a wrong label.

Stage 9's first risk-reduction step, and the plan is explicit about why it comes before the
framework: the interface strings are **data, not code**, so they move verbatim and get a test,
rather than being rewritten alongside a rebuild where a lost key would look like a styling bug.

`web/i18n/en.json` and `fr.json` are the source of truth. The shipped page still carries a copy
because it has no build step and keeps none, so the first test here is what stops the two
disagreeing while both exist. When the single-file page goes, its copy goes with it and these
files stay.

**The bug this removes by construction.** A prefix collision on `doc.` printed *Diagnostics* on
the Documents card, and nothing found it but a screenshot. Measured on the real table: `doc.` was
Diagnostics (5 keys) and `docs.` was Documents (40) — two namespaces one letter apart, one a
prefix of the other, meaning entirely different things. Anyone asked to change "the Documents
title" would reach for `doc.title` about half the time, and a lookup that groups by prefix without
the dot catches both.

Renamed to `diag.`, and `co.` (the company editor, 36 keys) to `company.` because it was a prefix
of both `col.` and `conn.`. 43 namespaces now, none a prefix of another — which is the assertion,
so the confusion cannot come back.

**And the same shape lived on one level deeper, in two places, because that assertion splits on the
first dot only.** `test_no_computed_family_is_shadowed_by_a_complete_key` found both on the run it
was written:

* `docs.no.*` — seven refusal strings looked up as `t("docs.no." + reason)` — beside the complete key
  `docs.none`. Renamed to `docs.refused.`;
* `prov.pf.*` — five probe states looked up as `t("prov.pf." + state)` — beside `prov.pfNothing` and
  `prov.pfSkippedWhy`, the second of which is *the explanation for `prov.pf.skipped`*, which is as
  confusable as a pair of keys gets. Renamed to `prov.probeNoTier` and `prov.probeSkipReason`.

Neither was live: both lookups carry the trailing dot, so only `reason == "ne"` or
`state == "Nothing"` could have reached the wrong string. The human half was live from the day each
was written, and the human half is what the original bug was made of — somebody asked to change "the
skipped explanation" reaches for either name about half the time.
"""

import json
import pathlib
import re

import pytest

I18N = pathlib.Path("web/i18n")
PAGE = pathlib.Path("corparius/webui.html")
LANGS = ("en", "fr")


def _json(lang: str) -> dict:
    return json.loads((I18N / f"{lang}.json").read_text(encoding="utf-8"))


def _page_tables() -> dict:
    """The `const I18N = {...}` block, parsed back out of the page.

    The same reader the extraction used, kept here rather than in a helper module: this is the one
    place that needs it, and a test that parses what it is checking is a test that cannot be fooled
    by a rewrite that happens to keep the file the same length.
    """
    lines = PAGE.read_text(encoding="utf-8").splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith("const I18N"))
    depth = 0
    for i in range(start, len(lines)):
        depth += lines[i].count("{") - lines[i].count("}")
        if depth == 0 and i > start:
            end = i
            break
    blob = "\n".join(lines[start : end + 1]).replace("const I18N = ", "", 1).rstrip(";")
    blob = re.sub(r"(?m)^(en|fr):", r'"\1":', blob)
    return json.loads(blob)


# --- the guard on the guard -----------------------------------------------------


def test_there_are_strings_to_check():
    """An empty read would make everything below vacuously true — the failure this project has
    already had once, when a flat glob quietly scanned fewer files than it looked like."""
    for lang in LANGS:
        assert len(_json(lang)) >= 400, f"{lang}.json has {len(_json(lang))} keys"
    assert set(_page_tables()) == set(LANGS)


# --- one source of truth --------------------------------------------------------


@pytest.mark.parametrize("lang", LANGS)
def test_the_page_carries_exactly_what_the_json_says(lang):
    """Key for key **and value for value**. The page has no build step, so the copy in it is
    written by hand or by a one-off script; this is the only thing that keeps the two from
    drifting apart while both exist, and a drift here is a label that is right in one place and
    wrong in the other."""
    assert _page_tables()[lang] == _json(lang)


def test_the_two_languages_have_the_same_keys():
    """The plan's key-set equality test. A key present in one language and not the other falls
    back silently to English, which reads as a translation nobody got round to rather than as the
    bug it is."""
    en, fr = _json("en"), _json("fr")
    only_en = sorted(set(en) - set(fr))
    only_fr = sorted(set(fr) - set(en))
    assert not only_en and not only_fr, f"en only: {only_en}; fr only: {only_fr}"


# --- the collision that shipped -------------------------------------------------


def _namespaces(table: dict) -> set[str]:
    return {k.split(".")[0] for k in table if "." in k}


def _computed_prefixes() -> set[str]:
    """Every prefix looked up at runtime — `t("ib.fix." + m.fix)` — across both front ends.

    The page **and** `web/src/*.svelte`, because the console is being rebuilt and a scan of the old
    one would quietly stop covering the new one file at a time. That is the failure this project keeps
    finding: a scanner that under-reports passes.
    """
    sources = [PAGE.read_text(encoding="utf-8")]
    sources += [
        p.read_text(encoding="utf-8") for p in sorted(pathlib.Path("web/src").glob("*.svelte"))
    ]
    return {
        prefix
        for source in sources
        for prefix in re.findall(r'\bt\("([a-z][a-z.]*\.)"\s*\+', source)
    }


def test_no_namespace_is_a_prefix_of_another():
    """The assertion that makes the `doc.`/`docs.` bug impossible rather than fixed.

    *Diagnostics* appeared on the Documents card, and only a real screenshot found it. Two
    namespaces one letter apart, meaning different things, with one a prefix of the other: a
    person asked to change "the Documents title" reaches for `doc.title` half the time, and code
    that groups by prefix without the dot matches both sets at once.

    Measured before the rename: `co`/`col`, `co`/`conn`, `doc`/`docs`. None now.
    """
    spaces = sorted(_namespaces(_json("en")))
    collisions = sorted(
        f"{a}. is a prefix of {b}." for a in spaces for b in spaces if a != b and b.startswith(a)
    )
    assert not collisions, (
        f"{collisions}. Two namespaces where one starts the other is how 'Diagnostics' ended up on "
        "the Documents card. Rename one so neither begins the other."
    )


def test_no_computed_family_is_shadowed_by_a_complete_key():
    """The same collision one level deeper, which the test above cannot see.

    `_namespaces` splits on the **first** dot, so it compares `docs` against `diag` and never looks
    inside either. Measured: the table shipped `docs.no.bad-name` … `docs.no.write-failed` — a family
    looked up as `t("docs.no." + reason)` — alongside the complete key **`docs.none`**. `docs.none`
    starts with `docs.no` and is not a member of the family, which is exactly the `doc.`/`docs.` shape
    that put *Diagnostics* on the Documents card.

    Not live: the lookup carries the trailing dot, so only `reason == "ne"` could have reached it. The
    human half was live from the day it was written — somebody asked to change "the no-documents
    message" picks `docs.no.` half the time — and that half is what the original bug was made of.

    Renamed to `docs.refused.`, and asserted here so the next family cannot be born shadowed. The rule
    is exact: for every prefix looked up at runtime, no key may start with it-minus-its-dot without
    being a member of the family.
    """
    en = _json("en")
    families = _computed_prefixes()
    assert families, "no computed prefix found: this guard would be vacuous"
    shadowed = sorted(
        f"{key!r} shadows the {prefix!r} family"
        for prefix in families
        for key in en
        if key.startswith(prefix.rstrip(".")) and not key.startswith(prefix)
    )
    assert not shadowed, (
        f"{shadowed}. A key that begins a computed prefix but is not in its family is the "
        "`doc.`/`docs.` bug in miniature: rename one so neither begins the other."
    )


def test_the_two_languages_agree_about_namespaces():
    """A namespace that exists in one language only is a card whose strings are half-translated,
    and the fallback hides it."""
    assert _namespaces(_json("en")) == _namespaces(_json("fr"))


def test_diagnostics_and_documents_are_no_longer_neighbours():
    """Named rather than implied, because the general rule above would still pass if someone
    reintroduced `doc.` for Documents and renamed Diagnostics to something else — which would be
    correct by the rule and confusing for the same reason."""
    en = _json("en")
    assert en["diag.title"] == "Diagnostics"
    assert "doc.title" not in en, "`doc.` is the namespace that caused the bug; it stays retired"
    assert en["docs.title"].startswith("What the company has")


# --- every string the page asks for exists --------------------------------------


def _referenced() -> set[str]:
    """Keys the page names literally.

    Only the literal ones, and that limit is the point: twelve lookups build their key at runtime
    (`t("ib." + m.kind)`, `t("col." + key)`, `t("prov.pf." + p.state)`), so a scan cannot know what
    they will ask for. This is why there is **no** "every key is used" ratchet here — it would
    report 128 live strings as dead. A guard that over-reports gets ignored, and an ignored guard
    is worse than none.
    """
    page = PAGE.read_text(encoding="utf-8")
    keys = set(re.findall(r'data-i18n(?:-ph|-title|-aria)?="([^"]+)"', page))
    keys |= set(re.findall(r'\bt\("([^"]+)"\)', page))
    keys |= set(re.findall(r"\bt\('([^']+)'\)", page))
    return {k for k in keys if not k.startswith("http")}


def test_every_literal_key_the_page_asks_for_exists_in_both_languages():
    """The direction that can be checked, and the one that shows as a raw key on screen: `t()`
    falls back to the key itself, so a missing string renders as `docs.folder` to an operator."""
    en, fr = _json("en"), _json("fr")
    referenced = _referenced()
    assert len(referenced) >= 300, f"the reference scan found only {len(referenced)}"
    missing_en = sorted(referenced - set(en))
    missing_fr = sorted(referenced - set(fr))
    assert not missing_en, f"the page asks for these and English does not have them: {missing_en}"
    assert not missing_fr, f"the page asks for these and French does not have them: {missing_fr}"


def test_the_computed_prefixes_all_have_at_least_one_key():
    """The part of "unused" that *can* be checked: a runtime lookup like `t("ib.fix." + m.fix)`
    needs its namespace to exist at all. An empty prefix is a card that renders raw keys for every
    row, which is the same visible failure as a missing string and just as silent in code."""
    en = _json("en")
    prefixes = _computed_prefixes()
    assert len(prefixes) >= 8, f"the computed-lookup scan found {sorted(prefixes)}"
    empty = sorted(p for p in prefixes if not any(k.startswith(p) for k in en))
    assert not empty, f"these prefixes are looked up at runtime and have no keys: {empty}"


# --- what the data itself must not contain --------------------------------------


def test_no_string_is_empty():
    """An empty value is worse than a missing key: the fallback never fires, so the label is blank
    on screen and the key looks present to every check that counts them."""
    for lang in LANGS:
        blank = sorted(k for k, v in _json(lang).items() if not str(v).strip())
        assert not blank, f"{lang} has empty strings: {blank}"


def test_the_untranslated_strings_are_the_ones_that_should_be():
    """21 keys where French equals English, and each is a word that does not translate — `Mode`,
    `Agent`, `console`, `CEO`, `tier.normal`, `CORP_UI_TOKEN`. Pinned as a count rather than
    forbidden, because forbidding it would push someone to translate `Plugins` into something
    nobody says, and leaving it unmeasured is how a genuinely forgotten string hides among them.
    """
    en, fr = _json("en"), _json("fr")
    same = sorted(k for k in en if en[k] == fr[k])
    # 20. Down to 19 when `progress.tokens` became *jetons* and `nav.providers` became *Fournisseurs*,
    # then back to 20 for `site.pages` — "{n} pages", which is the same word in both languages and is the
    # kind of entry this list exists to hold. A number that only ever goes up has stopped meaning
    # anything; so has one that is never allowed to.
    assert len(same) == 20, (
        f"{len(same)} keys are identical in both languages: {same}. If that is a word that does "
        "not translate, raise the number here and say which; if it is a forgotten string, "
        "translate it."
    )
