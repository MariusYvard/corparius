# Security policy

corparius is self-hosted and local-first. You run it, you own the data, and the
threat model is mostly about protecting that data on your own machine.

## Reporting a vulnerability

Please report privately, not in a public issue:

- Open a [GitHub security advisory](https://github.com/MariusYvard/corparius/security/advisories/new), or
- email the maintainer (see the address on the GitHub profile).

Include what you found, how to reproduce it, and the impact. Expect an
acknowledgement within a few days. Please give a reasonable window to fix before
any public disclosure.

## What to keep in mind when you run it

These are properties of the design, not bugs — but they matter to how you deploy.

- **The console binds `127.0.0.1` by default.** If you expose it (reverse proxy,
  a non-local `CORP_UI_HOST`), set `CORP_UI_TOKEN` so every call needs the
  `X-Corp-Token` header. The doctor fails loudly if you bind off-localhost with
  no token, because anyone who can reach it can spend money and publish.
- **The token covers reads as well as writes.** It used to guard mutations only,
  on the reasoning that nothing but localhost could reach the port. Setting a
  token is the operator saying otherwise, and at that point `/api/settings` and
  `/api/company` returning company configs, filesystem paths and which providers
  are configured is not a defensible default. With no token set, nothing
  changes: reads stay open and the first run needs no configuration.
- **Cross-site requests are refused without any configuration.** Binding
  localhost does not protect you from the browser you are already running: any
  page you visit can `fetch()` `http://127.0.0.1:8600`. Writes are refused
  unless `Sec-Fetch-Site` or `Origin` says the request came from the console's
  own page. Both headers are on the browser's forbidden list, so a hostile page
  cannot set them, and a client that sends neither — curl, a script, the MCP
  server — is allowed through, so nothing offline breaks. This is deliberately
  not a login screen or a CSRF token: a password in front of your own machine is
  the thing this console refuses to be.
- **`CORP_UI_ALLOWED_HOSTS` stops DNS rebinding.** A hostile domain can re-point
  its own name at `127.0.0.1`, at which point the browser considers the request
  same-origin and the `Origin` check passes — but the `Host` header still says
  the attacker's name. On a loopback bind, only loopback names are accepted.
  Bound off-loopback (Docker, a reverse proxy) any `Host` is accepted by default,
  because a strict list would break existing deployments on upgrade: **set
  `CORP_UI_ALLOWED_HOSTS` to the name you serve the console under.** It is read
  from the environment and `.env` only, never from the settings store, so a
  successful write to `/api/settings` cannot add a host to it.
- **Request bodies are capped at 1 MiB** and chunked bodies are refused, so a
  single request cannot exhaust memory.
- **Secrets at rest.** API keys saved from the console live in the SQLite store
  (`data/corparius.sqlite`) and are included in backups. By default they are
  stored in the clear. You can turn on at-rest encryption by setting
  `CORP_SECRET_KEY` (see [docs/securite.md](docs/securite.md)); it is off by
  default so the offline mock mode needs no dependency. On POSIX, corparius sets
  owner-only permissions (`0700` on the data dir, `0600` on the store); treat the
  file and its backups like a password regardless.
- **Live mode calls out.** The default mock mode makes no network calls. Enabling
  a cloud or free provider sends prompts to that provider — that is the point, but
  it is your data leaving the machine, under your keys.
- **The version check is opt-in.** `CORP_UPDATE_CHECK` is off by default; when on
  it makes a single request to the GitHub releases API and never downloads.

## Supported versions

corparius is pre-1.0; fixes land on `main` and in the next tagged release. Please
test against `main` before reporting.
