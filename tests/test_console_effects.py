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
