# Contributing to corparius

Thanks for considering a contribution. corparius is MIT-licensed, local-first, and
deliberately small. These notes keep it that way.

## Principles that are not up for negotiation

- **Local-first, no telemetry.** No unconsented network call in the product. The
  offline mock mode must always work with zero keys, zero models, zero network.
- **Auditable.** Prefer the standard library. Runtime dependencies are `requests`
  and `PyYAML`; anything heavier is optional, imported lazily, and off by default.
- **Safe by default.** The console binds `127.0.0.1`. Money, production code and
  publishing stay behind the human-in-the-loop gate.

## Setup

```bash
git clone https://github.com/MariusYvard/corparius.git && cd corparius
python -m venv .venv && . .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements-test.txt                # add -r requirements-dev.txt to build binaries
python -m pytest -q                                # ~280 tests, all offline
python start.py                                    # run the console locally
```

## Conventions

- **Code, comments and commit messages in English.** UI strings are bilingual
  FR/EN through `app/i18n.py` and the `data-i18n` attributes in `app/webui.html`.
- **`ruff format` decides layout; comments explain *why*, not *what*.** Run it
  before committing (`ruff format .`) — CI checks it.
- **Settings** are one row in `app/settings_spec.py`, not an HTML change; they
  resolve through the four layers in `app/cfg.py` (env > console/SQLite > `.env` >
  default).
- **Paths** go through `app/paths.py` so the source, Docker and frozen-binary
  builds agree on where things live.

- **New console endpoints go in the `ROUTES` table** in `app/webui.py`, not in a
  branch. A route is authenticated unless it says `public=True`, and the set of
  public ones is pinned by a test — if you add one, that test tells you.

## Before you open a pull request

```bash
python -m pytest -q          # green, with tests for new behaviour
ruff check .
ruff format --check .
mypy app/
```

- The offline mock mode still runs with no keys and no network.
- You did not add a runtime dependency without discussing it first (open an issue).
  `requests` and `PyYAML` are the whole runtime; test and lint tooling goes in
  `requirements-test.txt`.
- Docs updated if you changed behavior a user can see.

`mypy app/` is clean at the default level. The remaining ratchet is strictness:
`disallow_untyped_defs` is on for a few fully-typed leaf modules in
`pyproject.toml`, and adding a module to that list once it is fully annotated is
a welcome change on its own.

## Plugins

To extend corparius without changing the core — a new provider, tool, template or
agent tweak — write a plugin instead of patching the registries. Start from
`packaging/plugin-template/` and see `docs/plugins.md`. Propose it for one-click
install by opening a PR that adds it to `plugins/registry.json`; CI validates and
loads it. Plugins are off by default and curated by design.

## Reporting bugs and security issues

Open an issue for bugs and feature requests. For anything security-sensitive, do
**not** open a public issue — see [SECURITY.md](SECURITY.md).
