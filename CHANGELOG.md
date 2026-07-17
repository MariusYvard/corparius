# Changelog

## Unreleased — the console runs the whole thing

The console can now set everything corparius reads. No file needs a text editor.

### Read this before you upgrade

**Your `.env` starts working.** Nothing in the Python ever read it: `start.py`
copied `.env.example` into place and only docker-compose loaded it, so on the
documented `python start.py` path every line of that file was inert and the app
silently ran in mock mode. It is loaded now. If your `.env` says
`CORP_LLM_MOCK=false` with a cloud provider enabled, **the next start goes live
and spends money.** That is the fix working, so it is announced rather than
sprung: `start.py` prints the resolved mode before serving, and the doctor
reports it.

**Settings saved from the console used to vanish on restart.** They were written
to `os.environ` and to that unread `.env`. They are stored now, and survive.

**docker-compose no longer uses `env_file:`.** It injected every line of `.env`
into the process environment, the highest-precedence layer, which would leave the
settings screen entirely read-only. The `.env` mount is read directly instead, so
your values are unchanged; only their precedence is, in the direction that lets
the console work. The `loop` service gained the same mount.

**Two tests change meaning by design.** `test_providers_never_leak_keys_and_persist_env`
asserted that a saved key landed in `.env` and in `os.environ`; neither is true
now. See `tests/test_cfg.py` for the layering the suite asserts instead.

### Settings

- `app/cfg.py`: one resolver, four layers, highest wins — process environment,
  then settings saved from the console, then `.env`, then the default in the
  code. `.env` is deliberately not loaded into `os.environ`: that would outrank
  the console and silently ignore what the operator just saved.
- `Settings()` re-reads the environment. Every field evaluated `os.environ.get`
  at class-definition time, so a second instance handed back the values the
  process started with and every console edit looked inert. `_fresh_settings()`
  now does what its docstring always claimed.
- A settings screen driven by `app/settings_spec.py`: adding a setting is one
  row, not an HTML change. Each field shows which layer answers for it and goes
  read-only when the process environment pins it. Nothing is ignored in silence.
- Secrets are write-only and stored in the clear in `data/corparius.sqlite`, as
  they were in `.env`. They are therefore in `backup` zips; the panel and the
  doctor say so. The store is chmod 0600 on POSIX.
- The page sends `X-Corp-Token` and offers to enter one on a 401. Setting
  `CORP_UI_TOKEN` used to make the console read-only, because the client never
  sent the header.

### Company

- `app/company.py`: one loader, one validator, one atomic writer, shared by the
  CLI, the console and the MCP server. An empty `company.yaml` raised
  `AttributeError` from inside `setdefault(None)`; it now opens for repair with
  its problems named.
- A full editor: every field, including the eight the wizard hardcoded out of
  reach (price, billing, payment link, channels, pains, HITL tools, tokens per
  minute, ad budget). Saving rewrites the file from those fields, so hand-written
  comments are not kept.
- Delete asks you to type the slug and moves the config to `companies/.trash/`.
- `icp.channels` and `budgets.daily_ad_spend_eur` were written by the example and
  the wizard and read by nobody: every post claimed LinkedIn and every ad review
  claimed "0 EUR/day, within cap" whatever the config said. Both are wired up.

### Mail

- One account, both directions. Pick a provider, give the address and an app
  password; hosts and ports are derived. "Test this account" sends a real message
  and reads the real mailbox, and reports the two halves separately.
- **Port 465 never worked.** The code always called `starttls()`, but 465 is
  implicit TLS — and 465 is what Gmail, Fastmail and Infomaniak document. It
  failed with an error no operator could read.
- Diagnostics name the fix, not the protocol.
- `app/mailbox.py`: IMAP reading, read-only. corparius never marks a message
  seen, moves it or deletes it. `triage_inbox` returned a fixed "3 support,
  1 sales, 0 urgent" for every company, configured or not; it reads now.
- New `scan_replies` tool and an `outreach` table: the company knows which
  prospects answered. It could email people and never learn whether anyone
  replied, which is the one signal it exists to chase.

### Runtime

- **A `--loop` company was amnesiac.** `memory` was read once before the loop and
  never again, so it wrote an end-of-day summary every day and read none of them,
  planning each morning as if newborn. Verified over six days before and after.
  It is re-read at each day boundary, along with the settings.
- A loop can be started and stopped from the console. Stopping lands within a
  tick, and only the hours actually played are banked.
- Deploy, backup, a site headline and task editing are in the console. A deploy
  that published nothing was wrapped in `_ok()` and logged as a success; it now
  returns a failure and says which providers were skipped and why.
- The doctor gained the checks that matter: `.env` and its precedence, settings
  the environment shadows, secrets at rest, deploy order (`local` is always
  available, so anything after it never runs), and a **failure** when the console
  is bound off-localhost with no token.

### Design

- The blue ramp (#002FA7, #263F7F, #4C7EFF) carries structure. Selection is now a
  role of its own — focus, active tab, toggles, links — which is what leaves amber
  to mean the one primary action in view.
- What waits on your decision leads the pulse, reads sand, and takes you there.
- Motion conveys state: a view arrives once per navigation, a decision leaves the
  queue, a number travels to its new value. Nothing pulses or loops idle.
  `prefers-reduced-motion` collapses transitions **and** animations; it only ever
  killed transitions before.
