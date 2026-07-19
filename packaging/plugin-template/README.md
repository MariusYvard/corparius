# corparius plugin — example / template

A minimal, forkable corparius plugin. It registers a free LLM provider and a
deploy provider through the documented `register(api)` hook.

## Layout

```
corparius_plugin.json                 # manifest corparius reads (name, entrypoint, api_version, ...)
corparius_plugin_example/__init__.py  # register(api): your extensions
pyproject.toml                        # entry point: corparius.plugins
test_plugin.py                        # loads the plugin against corparius
```

## Make your own

1. Fork this directory into a new GitHub repo.
2. Rename the package `corparius_plugin_example`, and set `name` + `entrypoint` in
   `corparius_plugin.json` to match.
3. Implement `register(api)` — see the API list in `corparius_plugin_example/__init__.py`.
4. `pip install -e . && pytest` to check it loads.

## Install it in corparius

- **Drop-in (works everywhere, incl. the frozen binaries):** copy this directory
  into `<corparius-data>/plugins/<your-name>/`, set `CORP_PLUGINS_ENABLED=true`,
  restart. See the data location per OS in `docs/install.md`.
- **pip (source / Docker):** `pip install .` — the `corparius.plugins` entry point
  makes it discoverable.

Unverified plugins load only with `CORP_PLUGINS_ALLOW_UNVERIFIED=true`.

## Get it verified (one-click install for everyone)

Open a PR against corparius that appends your plugin to `plugins/registry.json`
(`name`, `repo`, `ref`, `sha256`, `kinds`, `description`). CI validates the
manifest, downloads your pinned ref, checks the SHA-256, and loads it against the
current API version. Once merged, anyone can install it from the console or with
`corparius plugin install <name>`. See `docs/plugins.md`.
