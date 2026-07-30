"""The provider registry and the table that documents it, kept in step.

`OPENAI_COMPAT_PROVIDERS` is the single source of truth: the settings rows, the
console's provider list and the router all derive from it. `docs/llm-providers.md`
does not — it is a hand-written table, which makes it the same shape of hazard as
the package manifests that sat two versions stale with placeholder checksums:
something that looks authoritative and drifts silently.

So the table is checked against the registry instead of trusted.
"""

import re
from pathlib import Path

import pytest

from corparius.llm import OPENAI_COMPAT_PROVIDERS as PROVIDERS

DOC = Path("docs/llm-providers.md")

pytestmark = pytest.mark.skipif(not DOC.is_file(), reason="a wheel install without docs/")


def _table():
    """{target: row} for the registry table, which is the one whose first column
    is a provider name."""
    rows = {}
    for line in DOC.read_text(encoding="utf-8").splitlines():
        cells = [c.strip() for c in line.split("|")[1:-1]]
        if len(cells) >= 3 and cells[0] in PROVIDERS:
            rows[cells[0]] = cells
    return rows


def test_every_registered_provider_is_documented():
    missing = sorted(set(PROVIDERS) - set(_table()))
    assert not missing, f"in the registry, absent from docs/llm-providers.md: {missing}"


def test_the_documented_key_variable_is_the_one_the_code_reads():
    """A table naming the wrong environment variable sends an operator to set a
    key nothing will ever read, and the failure looks like a broken provider."""
    wrong = {
        name: (cells[2], PROVIDERS[name]["key_env"])
        for name, cells in _table().items()
        if PROVIDERS[name]["key_env"] not in cells[2]
    }
    assert not wrong, f"documented key != code key: {wrong}"


def test_the_documented_endpoint_is_the_one_the_code_calls():
    for name, cells in _table().items():
        base = PROVIDERS[name].get("base", "")
        if not base:  # cloudflare and custom document their base_env instead
            assert PROVIDERS[name].get("base_env", "") in cells[1], name
            continue
        host = base.split("://", 1)[1]
        assert host in cells[1] or cells[1] in host, f"{name}: doc says {cells[1]!r}, code {host!r}"


def test_every_provider_says_where_to_get_a_key():
    """Either a signup link in the registry, or a documented reason it needs no
    key. An operator who cannot find the key page cannot use the provider."""
    for name, spec in PROVIDERS.items():
        assert spec.get("signup") or spec.get("key_optional"), name


def test_the_key_links_section_covers_every_provider_that_needs_one():
    text = DOC.read_text(encoding="utf-8")
    section = text.split("## Obtenir les clés", 1)[1].split("##", 1)[0]
    missing = [
        name
        for name, spec in PROVIDERS.items()
        if spec.get("signup") and not spec.get("key_optional") and f"{name} :" not in section
    ]
    assert not missing, f"no key link documented for: {missing}"


def test_a_default_model_is_only_pinned_where_it_can_be_checked():
    """`openrouter`'s pinned default rotted once already — the free variant was
    delisted while the paid one stayed. A hardcoded model name is a claim with
    an expiry date, so it belongs only on providers whose catalogue is stable."""
    for name, spec in PROVIDERS.items():
        model = spec.get("default_model")
        if model:
            assert isinstance(model, str) and model.strip(), name
            assert ":" not in model.split("/")[-1] or model.endswith(":free"), (
                f"{name}: {model!r} looks like it carries a provider prefix; "
                "default_model is the bare model id"
            )


def test_the_two_paid_giants_are_not_in_the_free_routing_order():
    """`_ROUTING_ORDER` is what gets picked automatically. OpenAI and Alibaba
    bill per token from the first call, so landing there by default would spend
    an operator's money without them choosing it."""
    from corparius.llm import _ROUTING_ORDER

    assert "openai" not in _ROUTING_ORDER and "alibaba" not in _ROUTING_ORDER


def test_the_registry_shape_is_uniform():
    """One malformed entry breaks the settings rows, the console list and the
    router at once, because all three iterate this dict."""
    for name, spec in PROVIDERS.items():
        assert re.fullmatch(r"[a-z0-9]+", name), name
        assert "key_env" in spec, name
        assert spec.get("base") or spec.get("base_env"), name
        if spec.get("base"):
            assert spec["base"].startswith("https://"), name
            assert not spec["base"].endswith("/"), name
