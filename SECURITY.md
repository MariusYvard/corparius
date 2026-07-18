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
  a non-local `CORP_UI_HOST`), set `CORP_UI_TOKEN` so every mutating call needs
  the `X-Corp-Token` header. The doctor fails loudly if you bind off-localhost
  with no token, because anyone who can reach it can spend money and publish.
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
