"""One rule, applied to every registry: check both ends of the wire.

The defect this closes has one shape and two faces, and it has cost this project
nine separate bugs.

*Produced and never consumed.* OpenRouter's `usage.cost` arrived on a response
already being parsed and was dropped. Ollama's own timings, the same. `icp.channels`
was written by the wizard and read by nobody, so every post claimed LinkedIn.
`architecture.input_modalities` arrived on the model catalogue and was thrown away
while the product told operators an image was "offered to the models that accept
images". A document's real length lived only inside an English sentence.

*Reachable and never reached.* `documents.images()` had no caller in the whole
codebase for two releases. `ask_operator` and `set_roster` sat in TOOLS with no
playbook, no queue and no declaration — one by design, one by omission, and nothing
could tell them apart. `_CEO_SCHEMA["model"]` was read by `_apply_directives` and
described to the model as a `string`, so the CEO answered "J'approuve" and wrote
nothing.

Every one of them was invisible: nothing failed, because nothing was looking at both
ends at once. So wherever the project keeps an explicit registry, this file asserts
that every entry is reached and everything reached is registered. It needs no
judgement, which is the point — the next one fails here instead of shipping.

The scarred registries keep their own files (test_tool_reach, test_ceo_powers,
test_images, test_inbox_remedy, test_readme); this one holds the uniform rule.
"""

import re
from pathlib import Path

import pytest

from corparius import inbox
from corparius.company import ROLES
from corparius.config import cfg, settings_spec
from corparius.providers.llm import OPENAI_COMPAT_PROVIDERS
from corparius.roster import ROSTER
from corparius.store.schema import MIGRATIONS, SCHEMA_VERSION
from corparius.tools.registry import TOOLS
from corparius.tools.spec import ROLE_TOOL

# `rglob`, and keyed by path rather than by filename.
#
# This scanned `glob("*.py")` — flat — and keyed by `p.name`. The package is flat today, so
# both spellings see the same 53 files and the difference is invisible. **The moment the
# first subpackage exists, the flat glob silently sees fewer files and nothing fails**: every
# "both ends of the wire" guarantee in this file quietly covers less, which would disarm the
# mechanism protecting the whole restructuring. Keying by bare filename has a second edge:
# two subpackages are eventually going to hold a `registry.py`, and one would overwrite the
# other in this dict.
#
# The count is pinned so narrowing cannot happen unnoticed. Bump it deliberately when a
# module is genuinely added or removed — never to make a red test go green.
SOURCES = sorted(Path("corparius").rglob("*.py"))
SRC = {p.relative_to("corparius").as_posix(): p.read_text(encoding="utf-8") for p in SOURCES}
ALL_SRC = "\n".join(SRC.values())
# 24 flat, +store/ (21: facade, base, schema, 18 mixins incl. reports) -store.py, + tools/ (4: __init__, spec, effects, registry)
# + kernel/ (10: __init__, crypto, dotenv, httpkit, i18n, paths, proc, records, text,
# vectors) + config/ (8: __init__, cfg, permissions, provider_table, secretbox, settings,
# settings_spec, store_layer — all but two moved in from the flat package).
MODULE_COUNT = 99


def test_every_source_file_is_scanned():
    """The guard on the guard. Everything below reasons over `SRC`, so a `SRC` that
    quietly shrank would weaken every assertion in this file without failing one."""
    assert len(SRC) == MODULE_COUNT, (
        f"{len(SRC)} modules scanned, expected {MODULE_COUNT}. If that is a real addition "
        "or removal, bump MODULE_COUNT; if it is not, something stopped being scanned."
    )
    assert len(SRC) == len(SOURCES), "two files collided on the same key"


# --- TOOLS: the mirror of test_tool_reach ------------------------------------


def test_every_tool_a_playbook_names_exists():
    """test_tool_reach asks whether every tool is reached. This asks the other
    way: a playbook naming a tool that does not exist is a role quietly doing one
    less thing than its author wrote down."""
    named = {name for spec in ROSTER.values() for name in spec.playbook}
    assert not sorted(named - set(TOOLS)), (
        f"playbooks name tools that do not exist: {named - set(TOOLS)}"
    )


def test_role_tool_maps_real_roles_to_real_tools():
    """It makes an untooled task executable. A bad value on either side makes a
    task that can never run, and the backlog shows it as approved."""
    assert not sorted(set(ROLE_TOOL) - set(ROLES)), "ROLE_TOOL keys are not all roles"
    assert not sorted(set(ROLE_TOOL.values()) - set(TOOLS)), "ROLE_TOOL points at missing tools"


# --- ROSTER against the roles a company may enable ---------------------------


def test_every_role_a_company_can_enable_has_an_agent():
    """`company.ROLES` is what the config and the console offer. A role an
    operator can switch on with nobody behind it is a switch that does nothing."""
    assert set(ROSTER) and {r.value for r in ROSTER} == set(ROLES)


# --- the settings registry ---------------------------------------------------


# Any uppercase key, and the call may be wrapped across lines. Both mattered: the
# first version of this pattern required a `CORP_` prefix and a single line, and so
# reported `CORP_HITL_TOOLS`, `GITLAB_TOKEN` and `NETLIFY_SITE_ID` as unread when all
# three are read — a detector that cries wolf is a detector nobody keeps.
_READ_IN_CODE = set(
    re.findall(r'cfg\.get(?:_int|_bool|_csv|_float)?\(\s*"([A-Z][A-Z0-9_]+)"', ALL_SRC, re.S)
)
# Provider and deploy keys are read through their own registry entry
# (`cfg.get(spec["key_env"])`), so the literal never appears next to a cfg call.
_READ_INDIRECTLY = {
    spec[field]
    for spec in list(OPENAI_COMPAT_PROVIDERS.values())
    for field in ("key_env", "base_env")
    if spec.get(field)
}


def test_every_setting_the_console_can_write_is_read_by_something():
    """A field the console offers and nothing reads is a dial wired to nothing —
    the operator turns it and the product does not change."""
    html = Path("corparius/webui.html").read_text(encoding="utf-8")
    unread = sorted(
        key
        for key in settings_spec.BY_KEY
        if key not in _READ_IN_CODE
        and key not in _READ_INDIRECTLY
        and key not in html
        and key not in cfg.BOOTSTRAP
    )
    assert not unread, f"settings the console writes and nothing reads: {unread}"


def test_every_setting_the_code_reads_can_be_set_somewhere():
    """The mirror: a value the code reads that the console cannot write and the
    docs never mention is a setting only its author knows about."""
    env_example = Path(".env.example")
    documented = env_example.read_text(encoding="utf-8") if env_example.is_file() else ""
    # Flat `glob` here on purpose, unlike the source scan above. This asks whether a
    # setting is documented *for an operator*, and an architecture decision record under
    # docs/adr/ is not that. Widening to `rglob` would make the test more permissive — more
    # places count as documentation, so fewer settings fail — which is the wrong direction.
    docs = "\n".join(p.read_text(encoding="utf-8") for p in Path("docs").glob("*.md"))
    readme = Path("README.md").read_text(encoding="utf-8")
    hidden = sorted(
        key
        for key in _READ_IN_CODE
        if key not in settings_spec.WRITABLE
        and key not in _READ_INDIRECTLY
        and key not in cfg.BOOTSTRAP
        and key not in documented
        and key not in docs
        and key not in readme
    )
    assert not hidden, f"settings nothing can set and nothing documents: {hidden}"


# --- providers ---------------------------------------------------------------


def test_every_provider_has_a_row_in_the_documentation():
    """The README states this as the rule for adding one: "New providers belong in
    the OPENAI_COMPAT_PROVIDERS registry with a documentation row in
    docs/llm-providers.md". A provider with no row has no limits, no signup link
    and no privacy note anywhere."""
    doc = Path("docs/llm-providers.md").read_text(encoding="utf-8")
    rows = {m.strip() for m in re.findall(r"^\| ([a-z]+) \|", doc, re.M)}
    missing = sorted(set(OPENAI_COMPAT_PROVIDERS) - rows)
    assert not missing, f"providers with no documentation row: {missing}"


def test_every_documented_provider_exists_in_the_registry():
    """The mirror: a row for a target the router cannot resolve sends an operator
    to create a key for nothing."""
    doc = Path("docs/llm-providers.md").read_text(encoding="utf-8")
    rows = {m.strip() for m in re.findall(r"^\| ([a-z]+) \|", doc, re.M)}
    # `local`, `cloud` and `claudecode` are targets without a registry entry.
    ghosts = sorted(rows - set(OPENAI_COMPAT_PROVIDERS) - {"local", "cloud", "claudecode"})
    assert not ghosts, f"documented providers the router does not know: {ghosts}"


@pytest.mark.parametrize("name", sorted(OPENAI_COMPAT_PROVIDERS))
def test_every_provider_declares_how_it_is_configured(name):
    spec = OPENAI_COMPAT_PROVIDERS[name]
    assert spec.get("key_env"), f"{name} has no key_env, so nothing can enable it"
    assert spec.get("base") or spec.get("base_env"), f"{name} has no endpoint"


# --- the store's migrations --------------------------------------------------


def test_there_is_one_migration_per_version_up_to_the_current_one():
    """A gap means a store from that version is opened, stamped forward and never
    actually migrated — the columns are missing and the failure surfaces much
    later, as a query."""
    assert sorted(MIGRATIONS) == list(range(1, SCHEMA_VERSION + 1))


# --- inbox fixes -------------------------------------------------------------


def test_every_fix_a_notice_files_is_in_the_registry():
    """`notify` drops an unknown fix with a warning, so the button silently never
    appears. The mirror direction (labels, next steps, real tabs) lives in
    test_inbox_remedy."""
    filed = set(re.findall(r'fix="([a-z_]+)"', ALL_SRC))
    assert not sorted(filed - set(inbox.FIXES)), (
        f"notices file unknown fixes: {filed - set(inbox.FIXES)}"
    )
