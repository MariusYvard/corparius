"""The console's polling effects, and the self-feeding loop one of them was.

**The measured defect.** On the built bundle, opening Operations made **105 requests in two seconds**
— five resources at roughly ten hertz, for as long as the tab stayed open. Cause: the load effect
calls `refresh()` synchronously, `refresh` reads `summary?.running` to decide whether to ask for the
activity log, and the same effect writes `summary`. So the effect depended on state it produced. And
because every re-run tore down its `setInterval` and made a new one, the five-second poll the
component's own docstring describes **never fired once** — the loop was both a flood and an outage,
which is why nothing looked wrong.

**What this file can and cannot hold.** The dependency was invisible: not a read on the effect's own
lines, but one a frame down a call it makes, and an effect tracks whatever it reads before its first
await. No static rule sees that, and the honest consequence is that these tests are *narrow*. They
pin the two lines whose removal brings the loop back, and they check the mechanical rule that does
generalise — an interval created in an effect must be cleared by it.

A runtime check would be better and is deliberately absent: it needs a browser, and the console's
build stays at two devDependencies so the wheel and the frozen binary serve the bundle with no Node.
The measurement is in the commit and in `Operations.svelte`; this is the ratchet under it.
"""

import pathlib
import re

import pytest

SRC = pathlib.Path("web/src")


def _components() -> dict[str, str]:
    found = {p.name: p.read_text(encoding="utf-8") for p in sorted(SRC.glob("*.svelte"))}
    assert len(found) >= 10, f"only {len(found)} components — the glob is wrong, not the console"
    return found


def _code(source: str) -> str:
    """The source with its comments removed.

    Written because the first version of `test_the_panel_is_kept_rather_than_rebuilt_on_every_switch`
    failed on the docstring that explains why the construct was removed — a rule that cannot tell
    code from the prose about code is a rule that punishes writing the prose.
    """
    without_block = re.sub(r"/\*.*?\*/", "", source, flags=re.S)
    without_markup = re.sub(r"<!--.*?-->", "", without_block, flags=re.S)
    return re.sub(r"^\s*//.*$", "", without_markup, flags=re.M)


def _effects(source: str) -> list[str]:
    """Every `$effect(() => { ... })` body, by brace matching.

    A regex cannot do this: the bodies contain object literals, arrow functions and template
    strings, and a greedy match runs to the end of the file while a lazy one stops at the first
    inner `}`. Counting depth is short and correct.
    """
    bodies = []
    for opened in (m.end() for m in re.finditer(r"\$effect\(\(\)\s*=>\s*\{", source)):
        depth, i = 1, opened
        while i < len(source) and depth:
            depth += (source[i] == "{") - (source[i] == "}")
            i += 1
        bodies.append(source[opened : i - 1])
    return bodies


# --- the loop that shipped ------------------------------------------------------


def test_the_operations_load_effect_untracks_its_loaders():
    """The pin. `refresh` reads `summary` and this effect writes it, so calling it tracked is a
    self-feeding loop — measured at 105 requests in two seconds. Non-vacuity is a one-line proof:
    delete the `untrack` from `Operations.svelte`, rebuild, and the rate goes back to ten hertz."""
    source = _components()["Operations.svelte"]
    loading = [b for b in _effects(source) if "refresh(" in b]
    assert loading, "no effect in Operations.svelte loads anything — this test is measuring nothing"
    for body in loading:
        if "setInterval" not in body:
            continue
        assert "untrack(" in body, (
            "the effect that both loads and polls must untrack its synchronous loaders: "
            "refresh() reads summary?.running, and this effect assigns summary"
        )
        # The interval callback is not part of the effect's synchronous body, so it is untracked
        # already — wrapping it too would be cargo. What must be inside is the first load.
        assert re.search(r"untrack\(\(\)\s*=>\s*\{[^}]*refresh\(\{\s*slow", body), (
            "the mount load is the tracked one; untracking only the poll fixes nothing"
        )


def test_untrack_is_imported_where_it_is_used():
    """A missing import here is not a type error in a `.svelte` file — it is `untrack is not
    defined` at runtime, on the tab, after the build succeeded."""
    for name, source in _components().items():
        if "untrack(" not in source:
            continue
        assert re.search(r"import\s*\{[^}]*\buntrack\b[^}]*\}\s*from\s*[\"']svelte[\"']", source), (
            f"{name} calls untrack without importing it from svelte"
        )


# --- the rule that generalises ---------------------------------------------------


def test_every_interval_an_effect_creates_is_cleared_by_it():
    """Mechanically checkable, and the half of the original defect that had teeth: an effect that
    starts a timer without returning a teardown leaks one per re-run, and a component that re-runs
    its effect — for any reason, including a legitimate company change — then polls twice, then four
    times. `clearInterval` in the returned function is the whole rule."""
    for name, source in _components().items():
        for body in _effects(source):
            if "setInterval" not in body:
                continue
            assert "clearInterval" in body, (
                f"{name}: an effect starts an interval and never clears it"
            )
            assert re.search(r"return\s*\(\)\s*=>", body), (
                f"{name}: clearInterval must be in the effect's returned teardown, not called inline"
            )


@pytest.mark.parametrize("name", ["Operations.svelte", "Providers.svelte", "Overview.svelte"])
def test_the_polling_tabs_still_have_an_effect_to_check(name):
    """The guard on the guard. Every assertion above is a loop over effects, so a component that
    stops matching passes all of them silently — which is the shape of the flat-glob failure this
    repository has already had once."""
    assert _effects(_components()[name]), f"{name} has no $effect the rules above can see"


# --- the other half of the same measurement --------------------------------------


def test_providers_does_not_make_its_table_wait_for_the_ollama_probe():
    """Measured on the same run: `/api/v1/providers` answers in 115ms and `/api/v1/ollama` in
    2289ms, because the latter looks for a daemon that is usually not installed. Under one
    `Promise.all` the tab said "Reading…" for 2.5 seconds to show a table that had been ready for
    2.4 of them. Three independent settles, so the slowest probe delays only its own card."""
    source = _components()["Providers.svelte"]
    load = source.split("async function load()", 1)[1].split("\n  }", 1)[0]
    assert "ollama" in load and "providers" in load, "the loader stopped fetching what it fetched"
    assert not re.search(r"await Promise\.all\(\[\s*get\(", load), (
        "a Promise.all of bare get() calls makes every card wait for the slowest probe"
    )
    assert load.count("settle(") >= 3, "each resource has to settle on its own"
    assert "oll.probing" in source, "a card that is empty for two seconds reads as a broken one"


# --- panels that survive being left ----------------------------------------------
#
# Measured on the built console, panel height in the frames after a click, before this rule existed:
#
#     operations   49px → 578px at 146ms → 610px at 238ms
#     providers    49px → 1479px at 149ms → 1598px at 2173ms   (the Ollama probe)
#     settings     49px → 1380px at 119ms
#     plugins      49px → 641px at 61ms
#
# Four of seven tabs opened as a 49-pixel shell and grew by a factor of twelve to thirty. `App.svelte`
# keyed the panel on the tab id, so every switch destroyed the component and rebuilt it from nothing —
# and the data was in `api.js`'s cache, so most of those refetches answered 304 and rebuilt a view
# that had been thrown away for free. After: **zero height changes on every tab, on every return**.
#
# The keying was there for a real reason — a component left mounted keeps polling — so these two tests
# are the pair. The first says panels are kept; the second says a kept panel stops polling.


def test_the_panel_is_kept_rather_than_rebuilt_on_every_switch():
    """The measurement above, as a rule. `{#key shown.id}` around the panel is what made a tab switch
    cost a full remount, so this pins the two halves of what replaced it: panels are rendered from a
    list of everything built so far, and the one that is not current is `hidden` rather than gone."""
    app = _code(_components()["App.svelte"])
    assert not re.search(r"\{#key\s+shown\.id\s*\}", app), (
        "the panel is keyed on the tab again: every switch throws the component and its data away"
    )
    assert "built.includes(entry.id)" in app, (
        "panels are no longer rendered from what has been built"
    )
    assert re.search(r"hidden=\{entry\.id\s*!==\s*tab\}", app), (
        "a panel that is not the current tab has to be hidden, not unmounted"
    )
    assert re.search(r"active=\{entry\.id\s*===\s*tab\}", app), (
        "a kept panel must be told whether it is the one in front of the operator"
    )


def test_a_kept_panel_stops_polling_when_it_is_not_the_one_in_front():
    """The other half, and the reason the remount existed in the first place. Keeping seven panels
    mounted is only affordable if six of them are quiet: without this, leaving Operations for
    Settings would leave five resources polling every five seconds against a view nobody is looking
    at, which is worse than the remount it replaced.

    The rule is mechanical — an effect that starts an interval must read `active` in its own body, so
    Svelte re-runs it on the way out and the teardown above clears the timer.
    """
    for name, source in _components().items():
        if name == "App.svelte":
            continue
        for body in _effects(source):
            if "setInterval" not in body:
                continue
            assert re.search(r"\bactive\b", body), (
                f"{name}: an effect polls without reading `active`, so the interval keeps running "
                "on a panel the operator has left"
            )


def test_every_tab_component_accepts_active():
    """Both ends. A component that never declares the prop reads `active` as undefined, which is
    falsy — so the test above would pass while the poller silently never started at all."""
    app = _components()["App.svelte"]
    tabs = re.findall(r"\{\s*id:\s*\"[a-z]+\",\s*component:\s*(\w+)\s*\}", app)
    assert len(tabs) >= 7, f"the TABS table stopped matching: {tabs}"
    for component in tabs:
        source = _components()[f"{component}.svelte"]
        props = source.split("$props()", 1)[0].rsplit("let {", 1)[-1]
        assert re.search(r"\bactive\b", props), f"{component}.svelte does not accept `active`"


def test_a_hovered_tab_is_built_before_it_is_clicked():
    """The half that covers the *first* visit, which persistence cannot.

    Measured with a 250ms hover before the click — what a mouse actually does — six of seven tabs
    then render at their full height in the first frame. Without it a cold click still opened on the
    49-pixel shell. `onfocus` as well as `onpointerenter`, or the keyboard path keeps the old
    behaviour and only mouse users get the fix.
    """
    app = _components()["App.svelte"]
    for handler in ("onpointerenter", "onfocus"):
        assert re.search(rf"{handler}=\{{\(\)\s*=>\s*want\(entry\.id\)\}}", app), (
            f"the tab button has no {handler} that builds its panel ahead of the click"
        )
    # And the load must not wait for `active`, or the prefetch prefetches nothing: a panel built on
    # hover is built *inactive*, and an effect that returns early on that fetches on the click after
    # all. This is the line that made the difference between 0 and 1 jumps on six tabs.
    for name in ("Documents.svelte", "Settings.svelte", "Plugins.svelte", "Providers.svelte"):
        source = _components()[name]
        loaders = [b for b in _effects(source) if "load(" in b and "setInterval" not in b]
        assert loaders, f"{name} has no load effect"
        for body in loaders:
            assert not re.search(r"if\s*\(\s*!?\s*active\s*\)\s*return", body), (
                f"{name}: the load effect gates on `active`, so hovering the tab loads nothing"
            )


def test_hidden_beats_the_display_rule_the_panel_also_carries():
    """**The defect this pair shipped, found by an operator in about a minute.**

    Panels stopped being unmounted and started being `hidden` — and `hidden` is a *user-agent* rule,
    so any author rule that sets `display` beats it. `main [role="tabpanel"]` sets `display: grid`,
    which is exactly that rule. Every panel rendered at once, stacked, and since Overview is built
    first and listed first, every tab showed Overview. The shipped page had
    `section[role="tabpanel"][hidden] { display: none }` for this reason and it did not come across
    with the markup.

    Worth saying why the measurement missed it: the probe asked each panel for its height *by id*, so
    seven panels each reported their own correct height and nothing asked how many were on screen at
    once. A measurement that queries what it expects to find cannot report what it did not think of —
    the browser check that replaced it counts visible panels.

    Same lesson as the scoped `.chat { min-height: 0 }` that beat a global rule, and the reason it is
    written as a rule rather than remembered: the winner has to be written where the loser lives.
    """
    # Through `_code`, because the comment above the rule *quotes the rule* — so the first version of
    # this test passed with the declaration deleted. That is the second time in one commit that an
    # assertion matched the prose explaining the code instead of the code, which is what `_code`
    # exists for and why it is used on every source this file reads.
    css = _code((SRC / "console.css").read_text(encoding="utf-8"))
    setter = re.search(r"^main \[role=\"tabpanel\"\][^\[].*display:\s*(\w+)", css, re.M)
    assert setter, "the panel no longer gets a display from CSS — this test is guarding nothing"
    assert setter.group(1) != "none"
    assert re.search(r"\[role=\"tabpanel\"\]\[hidden\]\s*\{[^}]*display:\s*none", css), (
        f"CSS gives every panel `display: {setter.group(1)}`, which beats the `hidden` attribute "
        "App.svelte uses to show one tab at a time: without a matching [hidden] rule every panel "
        "renders at once and every tab shows Overview"
    )


# --- the one value whose backup is somebody's memory ------------------------------


def test_the_passphrase_is_typed_twice_and_nothing_else_is():
    """**Why this field and not the other thirteen secrets.**

    Setting `CORP_SECRET_KEY` from the console re-encrypts every stored secret *immediately* and
    writes what was typed to `.env`. So a typo is not a failure an operator meets: the machine keeps
    working, on the typo, and their password manager is quietly wrong. They find out when they
    restore a backup somewhere else, which is the day nothing in the product can help them — the
    CLI's own warning says it plainly: "this is the only copy that opens your encrypted secrets".

    Every other destructive thing here is recoverable by construction and was already designed that
    way: a deleted company is moved to a trash folder and needs its slug typed, a document goes to
    `.trash/`, `restore` snapshots what it is about to overwrite *before* touching it, a plugin
    reinstalls at a pinned ref, and `secrets off` exists "so turning it on was never a trap". The
    passphrase is the one case where the guarantee cannot come afterwards, because the damage is not
    to the data.

    So exactly one field carries `confirm`. A second box on the thirteen pasted API keys would be
    friction that teaches an operator to click through the mechanism.
    """
    from corparius.config.settings_spec import BY_KEY

    confirmed = {key for key, spec in BY_KEY.items() if getattr(spec, "confirm", False)}
    assert confirmed == {"CORP_SECRET_KEY"}, confirmed

    source = _code(_components()["Settings.svelte"])
    assert "{#if f.confirm}" in source, "the flag is declared and the field does not read it"
    # The second box's contents must never reach the request. `edited` is what is sent; the
    # confirmation lives apart precisely so it cannot be.
    assert "repeated = $state({})" in source
    # The confirmation must never reach the request. The payload is built by walking `edited`, and
    # the only way the second box could join it is by being walked too — so that is what is
    # forbidden, rather than a window of characters around the call, which is what the first
    # version of this line measured and why it matched the *cleanup* on the line after.
    assert "Object.entries(edited)" in source
    assert "Object.entries(repeated)" not in source
    assert "{ values, unset }" in source, "the body is more than the two things built from `edited`"


def test_a_mismatch_refuses_the_whole_save_rather_than_dropping_the_field():
    """Dropping the one field would leave the operator looking at a saved settings page with no
    passphrase on it — indistinguishable from one where it worked, which is worse than the typo.

    And the confirmation is cleared with `edited`: a leftover would silently match the *next*
    passphrase typed into an empty box, which is the guard defeating itself.
    """
    source = _code(_components()["Settings.svelte"])
    body = source.split("async function save()", 1)[1][:400]
    assert re.search(r"if \(mismatched\.length\)", body), "save does not check the confirmation"
    assert "return;" in body.split("mismatched.length")[1][:120], "it checks and carries on anyway"
    assert "repeated = {};" in source, "a stale confirmation would match the next passphrase"
