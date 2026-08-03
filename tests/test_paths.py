"""Path resolution across the run modes packaging introduces: a source checkout
(the default, and what every other test relies on), an explicit CORP_HOME
override, a simulated frozen bundle, and a pip-installed wheel. The point is to
guarantee that running from source is byte-identical to the pre-packaging
behavior while a frozen build or an install redirects writable state to a per-OS
directory and finds its resources inside the package."""

import sys
from pathlib import Path

from corparius import company as company_mod
from corparius import documents, paths

REPO_ROOT = Path(paths.__file__).resolve().parent.parent


# --- source checkout: everything resolves to the repo layout, unchanged --------


def test_source_mode_resolves_to_repo_root(monkeypatch):
    # These three describe what resolves with no CORP_HOME set, so they take it
    # away themselves. The suite-wide fixture points it at an empty private home
    # precisely so no other test lands on the layout asserted here — the
    # checkout, which is writable and was being written to.
    monkeypatch.delenv("CORP_HOME", raising=False)
    assert paths.is_frozen() is False
    assert paths.user_home() == REPO_ROOT
    assert paths.resource_dir() == REPO_ROOT
    assert paths.companies_dir() == REPO_ROOT / "companies"
    assert paths.dotenv_file() == REPO_ROOT / ".env"
    assert paths.page_file() == REPO_ROOT / "corparius" / "webui.html"
    assert paths.example_company_src() == REPO_ROOT / "companies" / "example"


def test_source_mode_default_data_dir_is_cwd_relative(monkeypatch):
    # The historical default; the tests never reach it because conftest sets
    # CORP_DATA_PATH, but start.py / docker rely on it staying "./data".
    monkeypatch.delenv("CORP_HOME", raising=False)
    assert paths.default_data_dir() == "./data"


def test_page_file_is_readable():
    # The frozen build's main resource risk: the console HTML must be findable.
    assert paths.page_file().is_file()


# --- explicit override: CORP_HOME wins over everything -------------------------


def test_corp_home_override(monkeypatch, tmp_path):
    home = tmp_path / "corp-home"
    monkeypatch.setenv("CORP_HOME", str(home))
    assert paths.user_home() == home
    assert paths.companies_dir() == home / "companies"
    assert paths.dotenv_file() == home / ".env"
    # With an explicit home the data default becomes absolute, not cwd-relative.
    assert paths.default_data_dir() == str(home / "data")
    # Resources still come from the bundle/checkout, not the writable home.
    assert paths.resource_dir() == REPO_ROOT


# --- simulated frozen bundle ---------------------------------------------------


def test_frozen_mode(monkeypatch, tmp_path):
    monkeypatch.delenv("CORP_HOME", raising=False)
    bundle = tmp_path / "bundle"
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(bundle), raising=False)
    assert paths.is_frozen() is True
    assert paths.resource_dir() == bundle
    home = paths.user_home()
    assert home != REPO_ROOT
    assert home.name == "corparius"  # per-OS app-data dir
    assert paths.default_data_dir() == str(home / "data")


def test_frozen_mode_corp_home_still_wins(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setenv("CORP_HOME", str(tmp_path / "explicit"))
    assert paths.user_home() == tmp_path / "explicit"


# --- simulated pip install: no sibling resources, state off site-packages ------


def test_installed_mode_writes_state_off_site_packages(monkeypatch):
    """A wheel has no pyproject.toml beside the package, so user_home must not
    resolve to site-packages (where _REPO_ROOT points once installed); it falls
    to the per-OS directory, exactly as a frozen build does."""
    monkeypatch.setattr(paths, "_is_source_checkout", lambda: False)
    monkeypatch.delenv("CORP_HOME", raising=False)
    home = paths.user_home()
    assert home != REPO_ROOT
    assert home.name == "corparius"
    assert paths.default_data_dir() == str(home / "data")


def test_installed_mode_finds_resources_inside_the_package(monkeypatch, tmp_path):
    """When the repo-root resource is absent (an install has no sibling
    companies/ or plugins/), _resource falls back to the package's _data dir,
    where the wheel force-includes them."""
    # Point resource_dir at an empty tree so the primary location misses.
    monkeypatch.setattr(paths, "resource_dir", lambda: tmp_path)
    monkeypatch.setattr(paths, "_PACKAGE_DIR", tmp_path / "pkg")
    data = tmp_path / "pkg" / "_data" / "plugins"
    data.mkdir(parents=True)
    (data / "registry.json").write_text("{}", encoding="utf-8")
    assert paths.plugin_registry_file() == tmp_path / "pkg" / "_data" / "plugins" / "registry.json"


def test_resource_prefers_the_primary_location(monkeypatch, tmp_path):
    """When the repo-root/_MEIPASS copy exists (source or frozen), it wins and
    the _data fallback is never consulted."""
    monkeypatch.setattr(paths, "resource_dir", lambda: tmp_path)
    (tmp_path / "plugins").mkdir()
    (tmp_path / "plugins" / "registry.json").write_text("{}", encoding="utf-8")
    assert paths.plugin_registry_file() == tmp_path / "plugins" / "registry.json"


# --- first-run seeding of the example company ---------------------------------


def test_seed_examples_into_empty_home(tmp_path):
    slugs = company_mod.seed_examples(root=tmp_path)
    assert "example" in slugs
    assert (tmp_path / "companies" / "example" / "company.yaml").is_file()


def test_seed_examples_is_idempotent(tmp_path):
    company_mod.seed_examples(root=tmp_path)
    # A second call must not raise or duplicate.
    slugs = company_mod.seed_examples(root=tmp_path)
    assert slugs.count("example") == 1


def test_company_apps_dir_sits_next_to_the_config_it_belongs_to(monkeypatch, tmp_path):
    monkeypatch.setenv("CORP_HOME", str(tmp_path))
    assert paths.company_apps_dir("t") == tmp_path / "companies" / "t" / "apps"
    assert paths.company_apps_dir("t").parent == paths.company_skills_dir("t").parent


def test_where_a_company_lives_is_resolved_per_call_not_snapshotted(monkeypatch, tmp_path):
    """The third module to learn this, after backup.py and cli._store(): a
    module-level snapshot of a layered setting is a snapshot of the wrong layer.

    company.ROOT was captured at import while paths.companies_dir() resolved on
    every call, so the two agreed only as long as CORP_HOME was set before the
    import. The console had already grown an endpoint guarding a slug against one
    of them and building a path from the other. One source now, so they cannot
    disagree — and moving the folder is the same lever an operator pulls.
    """
    from corparius import company as mod

    assert not hasattr(mod, "ROOT"), "an import-time snapshot is what caused this"
    monkeypatch.setenv("CORP_HOME", str(tmp_path))
    (tmp_path / "companies" / "late").mkdir(parents=True)
    (tmp_path / "companies" / "late" / "company.yaml").write_text("slug: late\n", encoding="utf-8")
    # Set after the module was imported, and still honoured by both.
    assert mod.list_slugs() == ["late"]
    assert mod.path_for("late").parent == documents.folder("late").parent


def test_the_suite_is_hermetic_against_a_developer_who_runs_corparius(tmp_path):
    """CORP_HOME is what companies/, skills/ and .env hang off, and it is set on
    the machine of anyone actually using corparius.

    This has been wrong in both directions. Left alone, tests wrote into a real
    installation. Deleted, they wrote into the checkout instead — companies/t,
    companies/d and companies/m sat in the working tree gitignored, and a real
    orchestrator tick rewrote the tracked companies/example/company.yaml. What it
    points at now is an empty directory belonging to this test and nothing else.
    """
    import os

    home = Path(os.environ["CORP_HOME"])
    assert home == tmp_path / "home", "the hermetic fixture must own it"
    assert home != paths._REPO_ROOT, "the checkout is writable; tests must not land there"
    assert not (home / "companies").exists(), "empty: a copy cost 768 ms a test"
