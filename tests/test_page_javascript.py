"""The shipped page's 3 325 lines of script, checked by something that speaks JavaScript.

Nothing checked this before, and the commit that added this file is why it should. The `const I18N`
block is now **generated** from `web/i18n/*.json`. A generator that emitted a stray comma or an
unescaped quote would produce a page whose entire script fails to parse — the console would render
as unstyled markup with no behaviour at all — and every other test in this suite would still pass,
because none of them run JavaScript.

Two properties, and the second is the one Python cannot honestly assert:

  * the script **parses**, via `node --check`;
  * **no string renders as a raw key** in either language, evaluated through the page's own
    `t()` — which is `I18N[lang][k] ?? I18N.en[k] ?? k`, so a missing string shows an operator
    `docs.folder` where a label belongs. Asserting that in Python would mean writing a second copy
    of that expression and trusting it to stay in step with the one that ships.

**Skipped where node is absent**, and that is not a compromise: the runtime must never need it. The
wheel and the frozen binary serve this page with no Node installed, which the plan states
explicitly — Node is a development and CI tool, and the front-end build is the only thing that uses
it. CI has it, so this runs there.
"""

import json
import pathlib
import shutil
import subprocess

import pytest

PAGE = pathlib.Path("corparius/webui.html")
NODE = shutil.which("node")
# `encoding="utf-8"` on every call below, not `text=True` alone. The dump is 57 KB of JSON with
# accented French in it, and `text=True` decodes with the locale codepage — on Windows that is
# cp1252, which cannot read it. The failure is not an exception in the test: it is a reader thread
# dying inside subprocess and `stdout` arriving as None.
needs_node = pytest.mark.skipif(
    not NODE, reason="node is not installed; CI has it for the front-end build"
)


def _script() -> str:
    """The contents of the page's single `<script>` block."""
    page = PAGE.read_text(encoding="utf-8")
    body = page[page.index("<script") :]
    return body[body.index(">") + 1 : body.index("</script>")]


def test_there_is_a_script_to_check():
    """The guard on the guard. An extraction that silently found nothing would make both checks
    below pass on an empty file, which is the failure this project has had before."""
    assert len(_script().splitlines()) > 1000, "the script extraction found almost nothing"
    assert "const I18N" in _script()


@needs_node
def test_the_script_parses_as_javascript(tmp_path):
    js = tmp_path / "page.mjs"
    js.write_text(_script(), encoding="utf-8")
    done = subprocess.run(
        [NODE, "--check", str(js)], capture_output=True, text=True, encoding="utf-8", timeout=60
    )
    assert done.returncode == 0, f"the page's script does not parse:\n{done.stderr[-1500:]}"


@needs_node
def test_no_string_renders_as_a_raw_key_in_either_language(tmp_path):
    """Through the page's own lookup, run by a real engine.

    The probe is written to a file rather than passed with `-e`, because the block contains quotes
    and accented text in both languages and a shell would be one more thing between the assertion
    and what it is asserting.
    """
    script = _script()
    marker = "const I18N = "
    block = script[script.index(marker) + len(marker) :]
    block = block[: block.index("\n};") + len("\n}")]
    probe = tmp_path / "probe.mjs"
    probe.write_text(
        "const I18N = "
        + block
        + ";\n"
        + "const t = (lang, k) => I18N[lang][k] ?? I18N.en[k] ?? k;\n"
        + "const raw = {};\n"
        + "for (const lang of Object.keys(I18N)) {\n"
        + "  raw[lang] = Object.keys(I18N.en).filter(k => t(lang, k) === k);\n"
        + "}\n"
        + "const counts = Object.fromEntries("
        + "Object.entries(I18N).map(([l, v]) => [l, Object.keys(v).length]));\n"
        + "console.log(JSON.stringify({counts, raw}));\n",
        encoding="utf-8",
    )
    done = subprocess.run(
        [NODE, str(probe)], capture_output=True, text=True, encoding="utf-8", timeout=60
    )
    assert done.returncode == 0, done.stderr[-1500:]
    result = json.loads(done.stdout.strip().splitlines()[-1])

    # The same numbers `tests/test_i18n.py` asserts against the JSON, here proved against what a
    # browser would actually load. Two tables, one count: a language that lost a key would show up
    # as a smaller number here and as a raw key below.
    # 528: `prov.recheck` and `cfg.unsaved`, both added when a design review found a line reading
    # "58 · 7d" — two numbers with no sentence — and a Save button at the bottom of a 5 000px form with
    # nothing saying how much was unsaved.
    assert result["counts"] == {"en": 528, "fr": 528}, result["counts"]
    for lang, keys in result["raw"].items():
        assert not keys, f"{lang} would render these as raw keys on screen: {keys[:10]}"


@needs_node
def test_the_two_tables_are_the_ones_the_json_files_hold(tmp_path):
    """The JSON compared to what the engine actually loads.

    `test_i18n.py` reads the same block with Python's JSON parser after a small regex fixup. This
    reads it with the engine that ships it. The distinction is **not** duplicate keys — probed, and
    both catch those, because Python and JavaScript both take the last value. It is the constructs
    where the two parsers disagree: a trailing comma is legal in a JS object literal and illegal in
    JSON, so the Python side would report a broken table that a browser reads perfectly, and
    anything JS-only in there would fail the Python read while working in production.

    Belt and braces on purpose, and cheap: the page is the one artefact in this repository that no
    Python test can execute.
    """
    script = _script()
    marker = "const I18N = "
    block = script[script.index(marker) + len(marker) :]
    block = block[: block.index("\n};") + len("\n}")]
    probe = tmp_path / "dump.mjs"
    probe.write_text(
        "const I18N = " + block + ";\nconsole.log(JSON.stringify(I18N));\n", encoding="utf-8"
    )
    done = subprocess.run(
        [NODE, str(probe)], capture_output=True, text=True, encoding="utf-8", timeout=60
    )
    assert done.returncode == 0, done.stderr[-1500:]
    evaluated = json.loads(done.stdout.strip().splitlines()[-1])
    for lang in ("en", "fr"):
        on_disk = json.loads(pathlib.Path(f"web/i18n/{lang}.json").read_text(encoding="utf-8"))
        assert evaluated[lang] == on_disk, (
            f"{lang}: what the browser loads is not what the file says"
        )
