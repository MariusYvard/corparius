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
pip install -r requirements-dev.txt
python -m pytest -q                                # ~150 tests, all offline
python start.py                                    # run the console locally
```

## Conventions

- **Code, comments and commit messages in English.** UI strings are bilingual
  FR/EN through `app/i18n.py` and the `data-i18n` attributes in `app/webui.html`.
- **Style matches the surrounding code.** Comments explain *why*, not *what*.
- **Settings** are one row in `app/settings_spec.py`, not an HTML change; they
  resolve through the four layers in `app/cfg.py` (env > console/SQLite > `.env` >
  default).
- **Paths** go through `app/paths.py` so the source, Docker and frozen-binary
  builds agree on where things live.

## Before you open a pull request

- `python -m pytest -q` is green, and you added tests for new behavior.
- The offline mock mode still runs with no keys and no network.
- You did not add a runtime dependency without discussing it first (open an issue).
- Docs updated if you changed behavior a user can see.

## Plugins

To extend corparius without changing the core — a new provider, tool, template or
agent tweak — write a plugin instead of patching the registries. Start from
`packaging/plugin-template/` and see `docs/plugins.md`. Propose it for one-click
install by opening a PR that adds it to `plugins/registry.json`; CI validates and
loads it. Plugins are off by default and curated by design.

## Reporting bugs and security issues

Open an issue for bugs and feature requests. For anything security-sensitive, do
**not** open a public issue — see [SECURITY.md](SECURITY.md).
