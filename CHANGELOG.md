# Changelog

## Unreleased — the console holds up under load and under a hostile tab

- **Fixed: concurrent writes lost rows.** The console built a new SQLite
  connection per HTTP request and never closed it, while the run loop wrote from
  a background thread. Measured on twelve concurrent writers, nine died with
  `database is locked`. One shared connection now serves the process, guarded by
  a re-entrant lock, with WAL enabled for the read-only settings layer and the
  CLI. Sharing it *without* that lock is worse than the original bug — threads
  land inside each other's transaction and rows vanish with no error — so the
  lock is load-bearing. Concurrent polls during a run went from 635 to 1940.
- **Fixed: any web page you visited could drive the console.** Binding localhost
  never protected against the browser already running on it: a hostile tab could
  `fetch()` `http://127.0.0.1:8600` and start a run, save provider keys, publish
  the site or delete a company. Writes now require `Sec-Fetch-Site`/`Origin` to
  say the request came from the console's own page. **No configuration, no login
  screen, no CSRF token**, and clients that send neither header (curl, scripts,
  the MCP server) still work, so offline use is unchanged.
- **Fixed: DNS rebinding.** `CORP_UI_ALLOWED_HOSTS` (new, environment/`.env`
  only — never the settings store, which it protects) pins the `Host` names the
  console answers to. Loopback binds need nothing.
- **Breaking, if you run behind a reverse proxy:** a bind off-loopback now warns
  in `doctor` until `CORP_UI_ALLOWED_HOSTS` names your hostname. Requests with an
  unrecognised `Host` get a 403 that names the variable to set. Loopback and
  Docker-with-published-ports are unaffected.
- **`CORP_UI_TOKEN` now covers reads.** It guarded mutations only, so with a
  token set `/api/settings` and `/api/company` still served company configs,
  paths and provider status to anyone. With no token set, nothing changes.
- **Request bodies are capped at 1 MiB**, malformed `Content-Length` is a 400
  rather than a 500, chunked bodies are refused, and the token comparison is
  constant-time.
- **The Docker image runs as a non-root user** and carries a `HEALTHCHECK`.
- **The console's two 60- and 85-line `if/elif` dispatch chains are one route
  table.** That duplication was why the token check existed in one of them only;
  a route is now authenticated unless it opts out, and a test pins the public set
  so a new exception has to be written down.
- **CI runs the platforms we ship**: Python 3.10/3.12/3.14 on Linux, 3.12/3.14 on
  Windows, 3.12 on macOS. Adds `pyproject.toml` (tool configuration only) and
  tests for the previously untested toolbox, roster, approval gate and backups.
  171 tests → 243.

## Unreleased — a double-click start, accessible, no raw tracebacks

- **Double-click launchers.** `start-windows.bat`, `start-macos.command` and
  `start-linux.sh` bootstrap everything without a terminal, and say plainly what
  to install if Python is missing. `.gitattributes` forces LF on them so a
  Windows checkout does not ship a CRLF shebang that fails on macOS/Linux.
  `start.py` now handles a missing `python3-venv` and a failed pip with an
  instruction instead of a traceback.
- **Accessibility pass.** Audited across every tab: no unnamed buttons, no images
  without alt, no duplicate ids, `lang` set, tabs already keyboard-navigable. The
  four inputs that relied on a placeholder alone (site headline, mail test
  recipient, local-server preset, delete confirmation) got real `aria-label`s, so
  a screen reader names them and the label survives typing.
- **Unexpected errors are a sentence, not a traceback.** The console's 500
  handlers and the background run worker now show a localized "something went
  wrong, see the server log" rather than `str(exc)`; the full detail is logged.

## Unreleased — works on a phone, and a friendlier first launch

- **The console is usable on a phone.** Operations and Providers overflowed a
  390px screen because `.stack` was an implicit-`auto` grid: one wide card (the
  action-log table) stretched the whole column and every sibling with it.
  Constraining the track to `minmax(0, 1fr)`, plus stacking the provider rows and
  wrapping the approval card, brings horizontal overflow to zero on all tabs.
  Desktop is unchanged.
- **A port already in use is a sentence, not a traceback.** `start.py` and the CLI
  probe the port before binding (allow_reuse_address makes the bind result
  unreliable, especially on Windows) and say plainly that another console is
  likely running, with how to pick a free port. `ui` exits non-zero cleanly.

## Unreleased — fewer papercuts, and a CEO that can act

- **The CEO chat can do things, not only answer.** When the operator asks to run
  a day, publish the site, back up, or switch to their Claude subscription, the
  reply comes with a confirm button. One structured call classifies the intent
  and writes the reply (dogfooding the harness); the button calls the same
  audited endpoint the UI buttons use, so nothing runs on the model's say-so and
  money still hits the HITL gate. In mock or on a weak model it degrades to plain
  conversation. Intent classification is provider-agnostic via the harness.
- **Diagnosis strings are bilingual.** Testing mail, Claude, a provider or Ollama
  in a French console now answers in French; the CLI stays English. One
  `corparius/i18n.pick(lang, en, fr)` keeps both strings at the call site.
- **A proactive diagnostics banner.** If the doctor reports a failure on load,
  the console surfaces it with a link to the fix, instead of leaving it unseen in
  a tab. Dismissible per session.
- **`.env.example` slimmed** to the bootstrap keys plus the LLM tiers, with a
  pointer to the console and docs. The console sets everything else, so the file
  is no longer a wall to read.

## Unreleased — starter templates

- **The wizard offers a business to start from.** SaaS, online shop, agency,
  newsletter — each prefills the ICP, channels, price and the right agents, so a
  newcomer edits a starting point instead of facing a blank ICP and price. The
  typed name and product still win over the template's examples. Blank is still
  an option. Templates live in `corparius/company.py`, one source for the console.

## Unreleased — a guided first run

- **A "Getting started" thread on the overview.** A blank powerful tool is now a
  path: connect a model (or stay in mock), run a day, make a decision. Each step
  reflects real state and ticks itself off; the card removes itself when the
  three are done, or when hidden. Not a tour and not a modal (both banned), just
  an honest status list. Staying in mock counts as step one done, since running
  offline is a real choice, not an unfinished one; and only the operator's own
  approve/reject completes the last step, never the company's own task
  completions.
- **The offline sales site no longer shows mock gibberish.** In mock mode the
  draft is the echoed prompt; feeding it as the site's H1 made the product look
  broken on first use. It now falls back to the company's own tagline.

## Unreleased — plug in any LLM, get the same shape out

### Same structure, whatever the model

`corparius/structured.py` is a provider-agnostic harness: ask ten models to draft a
post and you get ten shapes (prose, JSON, JSON in a fence, a preamble, a
refusal); the harness returns one validated dict every time. It works at the
text level (instruct, extract, validate, repair once, then a deterministic
fallback) rather than on any provider's native structured-output feature,
because the 14 free tiers, Anthropic and the Claude CLI each support that
differently or not at all — relying on it would fragment the very thing this
unifies. A tool opts in with a `schema`; `draft_social_post` is converted as the
first. The MockProvider answers structured prompts offline, so structure holds
with no network. The fallback keeps the agent turn alive when a weak local model
cannot produce JSON at all.

### Plug in an LLM without a shell

- **Use your Claude subscription in one press.** A card in Providers tests the
  `claude` CLI, then flips mock off, cloud on, Claude Code on, and points the
  tiers at `claudecode:`. It was four scattered settings plus hand-edited tier
  strings that nobody found. **Windows fix:** the CLI npm installs is
  `claude.cmd`, which subprocess cannot launch by bare name (WinError 2), so
  `claudecode:` was broken on Windows; every caller now uses the resolved path.
- **A Test button on every free-tier provider.** One minimal real call, a
  readable verdict, the fix named instead of the HTTP status. The 14 tiers were
  wired already; this is how you tell a good key from a typo.
- **Ollama from the console.** A card shows what is installed and which tier
  models are missing, and pulls them in the background.
- **Local server presets.** LM Studio, Jan, Ollama's OpenAI endpoint, llama.cpp,
  vLLM and LocalAI fill the `custom:` endpoint from a dropdown.

### Design: blue, not yellow

The interface was too warm — ivory text and an amber accent read as a generic AI
dashboard. It is now one blue instrument: the owner's blue ramp carries
structure, action and selection; the only non-blue accents are petrol for health
and red for danger. Ivory and amber are gone. See DESIGN.md.

Also fixed: a `locale`/`stateBadge` scope bug introduced when render() was split,
which threw on every log render and surfaced as a connection-error banner.

## Earlier unreleased — the console runs the whole thing

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

- `corparius/cfg.py`: one resolver, four layers, highest wins — process environment,
  then settings saved from the console, then `.env`, then the default in the
  code. `.env` is deliberately not loaded into `os.environ`: that would outrank
  the console and silently ignore what the operator just saved.
- `Settings()` re-reads the environment. Every field evaluated `os.environ.get`
  at class-definition time, so a second instance handed back the values the
  process started with and every console edit looked inert. `_fresh_settings()`
  now does what its docstring always claimed.
- A settings screen driven by `corparius/settings_spec.py`: adding a setting is one
  row, not an HTML change. Each field shows which layer answers for it and goes
  read-only when the process environment pins it. Nothing is ignored in silence.
- Secrets are write-only and stored in the clear in `data/corparius.sqlite`, as
  they were in `.env`. They are therefore in `backup` zips; the panel and the
  doctor say so. The store is chmod 0600 on POSIX.
- The page sends `X-Corp-Token` and offers to enter one on a 401. Setting
  `CORP_UI_TOKEN` used to make the console read-only, because the client never
  sent the header.

### Company

- `corparius/company.py`: one loader, one validator, one atomic writer, shared by the
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
- `corparius/mailbox.py`: IMAP reading, read-only. corparius never marks a message
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
