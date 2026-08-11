"""The design tokens, ported verbatim, and held to the page they came from.

The plan's instruction for the CSS is the same as for the strings: **data, not code.** These ramps
were measured — `DESIGN.md` carries the reasoning, the inline comments carry the numbers, and one of
them exists because a dark pricing band shipped at **1.16:1**, near-black on near-black, which no
code in the repository could have caught because nothing knew what contrast was.

So `web/src/tokens.css` is a copy of the page's `:root` blocks rather than a rewrite into a
framework's theme system, and this file fails if the two disagree. When the single-file page goes,
its copy goes and these stay.

Every rule in the new components uses `var(--…)`. That is asserted rather than trusted, because a
hard-coded colour is exactly the thing that looks fine in the theme it was written in and wrong in
the other one — and the console has both.
"""

import pathlib
import re

import pytest

PAGE = pathlib.Path("corparius/webui.html")
TOKENS = pathlib.Path("web/src/tokens.css")
COMPONENTS = sorted(pathlib.Path("web/src").glob("*.svelte"))


def _themes(text: str) -> dict[str, dict[str, str]]:
    """The token blocks, keyed by which theme they set.

    **Per block, not flattened.** The first version of this collapsed every declaration into one
    dict, and because both themes define the same 23 names the light values simply overwrote the
    dark ones — so a test that claimed to compare the palette compared half of it. Classified by the
    selector's tail rather than its full text, because the page's `:root, [data-theme="dark"]` sits
    on a line the regex reaches back into and the port's does not.
    """
    import re

    out: dict[str, dict[str, str]] = {}
    for selector, body in re.findall(r"([^{}]*)\{([^{}]*?--[^{}]*?)\}", text, re.S):
        decls = {
            name: " ".join(value.split())
            for name, value in re.findall(r"(--[a-z0-9-]+)\s*:\s*([^;}]+)", body)
        }
        if not decls:
            continue
        selector = " ".join(selector.split())
        if selector.endswith('[data-theme="light"]'):
            key = "light"
        elif selector.endswith('[data-theme="dark"]'):
            key = "dark"
        else:
            key = "root"
        out.setdefault(key, {}).update(decls)
    return out


def test_there_are_tokens_to_check():
    """The guard on the guard: an empty read would make the comparison below vacuously true."""
    assert TOKENS.is_file(), "the tokens were never extracted"
    themes = _themes(TOKENS.read_text(encoding="utf-8"))
    # Measured: 25 in the dark block, 23 in the light one, 4 motion durations in `:root`.
    assert sorted(themes) == ["dark", "light", "root"], sorted(themes)
    assert len(themes["dark"]) == 25 and len(themes["light"]) == 23, {
        k: len(v) for k, v in themes.items()
    }


def test_every_token_matches_the_page_it_came_from():
    """Verbatim means verbatim, in **both** themes. A value that drifted would give an operator one
    console in the measured palette and one in something near it, which is the worst of both."""
    page_text = PAGE.read_text(encoding="utf-8")
    page = _themes(page_text[: page_text.index("</style>")])
    ported = _themes(TOKENS.read_text(encoding="utf-8"))
    for theme, declarations in ported.items():
        drifted = {
            name: (page[theme].get(name), value)
            for name, value in declarations.items()
            if page[theme].get(name) != value
        }
        assert not drifted, f"{theme}: these differ from the page: {drifted}"
    assert ported["dark"] != ported["light"], "the two themes cannot be the same block"


def test_both_themes_came_across():
    """A single-theme port would look right on the machine it was written on and be unreadable on
    the other. The light theme is the one that gets forgotten, so it is named."""
    text = TOKENS.read_text(encoding="utf-8")
    assert '[data-theme="light"]' in text
    assert '[data-theme="dark"]' in text
    assert "--ui-chroma" in text, "the knob that makes 'turn the colour off' still legible"


@pytest.mark.parametrize("path", COMPONENTS, ids=lambda p: p.name)
def test_no_component_hard_codes_a_colour(path):
    """Tokens or nothing. A literal colour is fine in whichever theme it was chosen against and
    wrong in the other one, and this console ships both."""
    style = path.read_text(encoding="utf-8")
    style = style[style.index("<style>") :] if "<style>" in style else ""
    literals = re.findall(r":\s*(#[0-9a-fA-F]{3,8}|rgb\(|rgba\(|hsl\(|oklch\()", style)
    assert not literals, (
        f"{path.name} writes colours directly: {sorted(set(literals))}. Every colour is a token; "
        "see web/src/tokens.css."
    )


@pytest.mark.parametrize("path", COMPONENTS, ids=lambda p: p.name)
def test_every_component_label_is_a_key_that_exists(path):
    """`t()` falls back to the key itself, so an invented one renders `ops.needsYou` on screen where
    a label belongs.

    This is here because the first draft of `Overview.svelte` invented eleven keys — `hitl.approve`,
    `ops.needsYou`, `progress.tick` among them — none of which are in the table. Checking against
    the data is a second's work and the alternative is finding it in a screenshot.
    """
    import json

    en = json.loads(pathlib.Path("web/i18n/en.json").read_text(encoding="utf-8"))
    missing = sorted(k for k in _keys_asked_for(path.read_text(encoding="utf-8")) if k not in en)
    assert not missing, f"{path.name} asks for keys that do not exist: {missing}"


def _keys_asked_for(source: str) -> set[str]:
    r"""Every literal key inside a `t(...)` call, ternaries included.

    This was `t\("([a-z][a-zA-Z.]*)"\)` — a key followed immediately by the closing paren — and it
    was blind to the form the second tab uses eight times:

        t(fact.pinned ? "mem.unpin" : "mem.pin")

    Neither key is followed by `)`, so neither was checked, and the guard reported a clean file while
    checking a fraction of it. The same silent narrowing as the flat `glob` and the stale mypy
    override: a scanner that under-reports **passes**, which is the worst way round.

    So: the arguments of every `t(` that contains no nested call, then every string literal in them.
    Concatenations like `t("ib." + item.kind)` contribute their literal prefix, which is not a key —
    the namespace check below is what covers those, and a prefix ending in `.` is skipped here.

    Every other string literal inside a `t(` **is** treated as a key, and that is deliberate rather
    than a limitation. It first reported `approved` from
    `t(decision === "approved" ? "toast.approved" : "toast.rejected")` — a comparison operand, not a
    key. The rule it enforces is that a `t()` call contains keys and nothing else, which is worth
    having: the alternative is a scanner that has to understand JavaScript to decide what a string is
    doing, and the call site reads better with the comparison lifted out.
    """
    keys = set()
    for arguments in re.findall(r"\bt\(([^()]*)\)", source):
        literals = re.findall(r'"([a-zA-Z][a-zA-Z0-9.]*)"', arguments)
        # `t("ob." + step.key + "Cta")` — a prefix **and** a suffix around a variable. Both literals
        # are fragments rather than keys, and this reported `Cta` and `Hint` as invented ones. That
        # form is checked by `_computed_families` below; here it is skipped.
        if len(literals) == 2 and literals[0].endswith("."):
            continue
        for literal in literals:
            if not literal.endswith("."):
                keys.add(literal)
    return keys


def _computed_families(source: str) -> list[tuple[str, str]]:
    r"""The `t("prefix." + x + "Suffix")` forms, as (prefix, suffix) pairs.

    A third lookup shape, after the literal and the bare prefix. The onboarding thread renders three
    keys per step out of one loop — `ob.model`, `ob.modelHint`, `ob.modelCta` — which is what makes the
    step key the only thing a client has to know about it. Unchecked, a typo in either fragment shows
    three raw keys per row at once.
    """
    return re.findall(r'\bt\("([a-z][a-z.]*\.)"\s*\+[^()"]*\+\s*"(\w+)"\)', source)


@pytest.mark.parametrize("path", COMPONENTS, ids=lambda p: p.name)
def test_every_computed_family_has_keys_at_both_ends(path):
    """A prefix and a suffix that between them name nothing is a row of raw keys on screen."""
    import json

    en = json.loads(pathlib.Path("web/i18n/en.json").read_text(encoding="utf-8"))
    for prefix, suffix in _computed_families(path.read_text(encoding="utf-8")):
        assert any(k.startswith(prefix) and k.endswith(suffix) for k in en), (
            f"{path.name}: t({prefix!r} + x + {suffix!r}) matches no key"
        )


def test_the_scanner_sees_a_prefix_and_suffix_pair():
    """The guard on the guard, and it earned its place: the scanner read `Cta` as a key first."""
    assert _computed_families('t("ob." + step.key + "Cta")') == [("ob.", "Cta")]
    assert _keys_asked_for('t("ob." + step.key + "Cta") t("a.one")') == {"a.one"}


def test_the_scanner_sees_a_key_in_a_ternary():
    """The guard on the guard, and it exists because the first version of the scanner did not.

    Non-vacuity for a source scanner cannot be shown by reintroducing a defect in the product — the
    defect is *in the scanner*. So it is stated directly: these three forms all reach the table.
    """
    found = _keys_asked_for('t(x ? "a.one" : "a.two") t("b.three") t("c." + y) t(z)')
    assert found == {"a.one", "a.two", "b.three"}, found


def test_the_computed_prefixes_the_components_use_have_keys():
    """`t("ib." + item.kind)` cannot be checked as a literal, but its namespace can: an empty prefix
    renders a raw key for every row, which is as silent in code as a missing string."""
    import json

    en = json.loads(pathlib.Path("web/i18n/en.json").read_text(encoding="utf-8"))
    for path in COMPONENTS:
        for prefix in re.findall(r't\("([a-z][a-z.]*\.)"\s*\+', path.read_text(encoding="utf-8")):
            assert any(k.startswith(prefix) for k in en), f"{path.name}: {prefix} has no keys"
