# The operator console

Vite + Svelte 5. **A development and CI tool only** — the wheel and the frozen binary serve the
built output with no Node installed, which is the promise the restructuring plan makes explicitly.

```bash
cd web
npm install          # once
npm run build        # writes ../corparius/api/static/
npm run dev          # a dev server on :5173, proxied to a running core
```

Then `python -m corparius.cli ui` and open **`/app/`**. The single-file console is still at `/`, and
stays there until this one replaces it.

## Where the output goes, and why it matters

`outDir` is `../corparius/api/static/`, **inside the package**. That is the same decision
`webui.html` already embodies: `paths._resource("corparius", ...)` finds a resource inside the
package in all three distribution modes — beside the package from a checkout, under `sys._MEIPASS`
when frozen, inside `site-packages` from a wheel — with no fallback and no per-mode special case.
Writing beside the package would have needed the `_data/` fallback that `companies/` and `plugins/`
need, for nothing.

The directory is **not tracked**. It is declared as a wheel artifact and in the PyInstaller spec,
and CI builds it before either packages anything. A checkout that has never run `npm run build`
simply has no `/app/`, which `paths.console_built()` reports and the route says out loud.

## The two things this console does not do

**It does not fetch anything from outside the core that served it.** No CDN, no font, no analytics.
`tests/test_console_bundle.py` pins that: the only absolute URLs allowed in the bundle are the XHTML
namespace and Svelte's own `svelte.dev/e/` links inside warning strings, both of which are text and
not requests.

**It does not carry every language.** English is in the bundle because `t()` falls back to it for
every key in every language; French is a chunk fetched when chosen, and awaited before the first
paint so nobody watches English flash past. Measured with both inlined: 91 132 bytes, of which
57 325 were the two tables — 63%, half of it a language most operators never select.

## The strings

`web/i18n/en.json` and `fr.json` are the source of truth, imported as data. The single-file page
carries a generated copy and `tests/test_i18n.py` fails if the two disagree, key for key and value
for value, so neither can drift while both exist.

525 keys each, 43 namespaces, and **no namespace is a prefix of another** — that last one is an
assertion, not a convention: `doc.` (Diagnostics) and `docs.` (Documents) once coexisted and printed
*Diagnostics* on the Documents card, which only a screenshot found.

## The tabs, one at a time

Rebuilt one tab per commit, so each can be looked at in a browser as it lands. A styled empty frame
would say less about whether the direction is right than one page an operator can read.

**"Done" here means every card named in the row, and nothing else.** The shipped page has seven tabs
carrying about thirty cards between them; a row that said "done" while three of eight cards existed
would be the kind of claim this project spends its tests refusing. So the table is a map of where
each card landed, and what is still only in the old page.

| Tab | Rebuilt | Still only in `webui.html` |
| --- | --- | --- |
| Overview | what needs you · the pulse · the run | Getting started · Go live · Sales site · Spend by agent · Payments · Recent activity |
| Operations | the board · standing rules · memory · drafts · the action log | — (Backup moved to Settings, below) |
| Documents | the drop zone · what is on file · reading one | — |
| Providers | Claude subscription · runtime toggles · free tiers · routing tiers · Ollama status and pull · preflight and the full sweep | — |
| CEO | — | the chat, and the CEO's own powers |
| Settings | the 80-field registry (generated) · Backup · theme and accent | — |
| Plugins | — | the seven seams · Skills |

Recent activity and Spend by agent are the two Overview cards with a v1 resource already behind them
(`activity`, and `spend_by_agent` inside `summary`), so they are the cheapest to bring across. Go live
and Sales site need `/api/golive` and `/api/site` versioned first. Naming that here rather than
discovering it per tab.

### The two long operations are durable jobs now

The Ollama **pull** and the preflight **sweep** were the last two things in `UiState` that a restart
silently lost, and the last two a second client could not see. They are `jobs` rows, like a run:

* **the guard is the store** — "a sweep is already running" read this process's memory, so one left
  behind by a crashed console was invisible to the next, which would cheerfully start a second:
  hundreds of duplicate paid calls;
* **stopping is a column**, not a `threading.Event`, so a phone can stop a sweep this console started;
* **one a dead console left behind reports `interrupted`** — with the progress line it had reached,
  because that is a column too. Nothing is resumed: restarting hundreds of paid calls unasked would be
  indefensible, and "interrupted, start it again" is what an operator can act on.

`GET /api/v1/machine` is the read, and it is the **only** poll on this tab — armed only while a job is
running, because a poll against no work is a round trip whose best case is that nothing changed.

The proof is the one the plan names for runs, run for real: write a `running` sweep row from the test
process, start a console as a **subprocess**, and read back `interrupted`. It needs no provider and no
network, which matters — a sweep is hundreds of paid generations, and a test that made one would be
charging whoever ran it.

The sweep asks before it spends. `{"estimate": true}` answers how many calls it would make **without
making any**, and that number goes in front of the operator first: NVIDIA alone advertises 102 models,
and "check everything" is their money and their rate limits.

### The settings form is generated, not written

80 fields across eight groups, and `Settings.svelte` names not one of them. `GET /api/v1/settings`
describes each — type, group, default, bilingual label and help — and the component renders what it is
given. A hand-written form would be a second copy of the registry, and this project has already paid
for that twice: a field the console offered that nothing read, and a value the code read that the
console could not set.

Three facts the payload carries because a client cannot derive them:

| field | why it cannot be inferred |
| --- | --- |
| `value: null` for a secret, plus `configured` | a payload echoing a credential puts it in every cache and proxy log |
| `editable` = `source !== "env"` | the process environment outranks the console, so the field is shown **disabled with the reason** rather than offered and silently ignored |
| `restart_required` | a bootstrap key lands in `.env` because it must be readable before the store opens, so it applies next start |

Clearing is not blanking. An empty registry field goes in `unset`, which deletes the row so the layer
below shows through — what asking for the default means. A provider credential is the opposite, and
lives on the Providers tab for that reason: a blank one stays stored, because clearing the row would
let `.env` resurrect a key just revoked.

**And the theme is stored on the server**, not in the browser. `settings.desc` claimed
"Stored in this browser only; they change nothing on the server", which was false: `ui_theme.json`
lives under the data path and its own docstring says that is what makes the theme follow the operator
across browsers. Corrected in both languages. The rebuilt console also never wrote `data-theme`, so a
light-mode operator got dark whatever they chose — `tokens.css` treats `:root` as dark and keys light
off the attribute.

### Every probe is a button

Nothing on the Providers tab opens a socket until an operator presses something. The rule was written
after `/api/providers` opened one on every refresh, and it is why the read reports `claude_installed`
from the filesystem and omits the Claude tier plan entirely — building that plan needs to know whether
Ollama answers, which on a machine without it costs a connect timeout per poll.

`test_the_reads_open_no_socket` holds it, by patching `socket.socket.connect` to raise. It calls the
services directly rather than over HTTP, because the first version went through the test client and
caught **the request itself** — a request *is* a socket, so it was measuring the trip.

One thing measured while writing this tab, worth knowing: `connected_providers()` answers `["ovh"]` on
a machine with **no credentials at all**. OVH AI Endpoints is key-optional and carries a default base
URL, so "use recommended routing" works on a fresh install before the operator has pasted anything.

**Overview reads three v1 resources and writes to three more.** `summary` (2 859 bytes, polled),
`jobs` (the durable run), and `companies`; it posts to `approvals`, `inbox` and `runs`. Every one of
those writes moved to v1 *because this tab needed it* — the plan's "reads first, writes when a v1
client has a decision to make", and a v1 client now does.

**Operations reads five and writes to four**, and the cadence differs per resource because that is
the whole point of having split them:

| Resource | When |
| --- | --- |
| `summary`, `tasks` | every poll — they change on every tick |
| `activity` | only while a run is going. A log nobody writes to is a request for 304s |
| `memory`, `drafts` | on mount, and after a write that touches them |

An unchanged v1 GET answers 304 with no body, so a poller that keeps its validator re-downloads
nothing — but a 304 is still a round trip, and not asking is cheaper than asking cheaply.

Two things the old page put on this tab and this does not. **Backup** goes to Settings: it is a
maintenance action that happened to be rendered next to the audit log, and "by layer, not by page" is
the rule that keeps a tab from being a reason for unrelated things to live together. **The approval
queue** leads Overview, because the human gate is the subject of this product and should not have to
be looked for — what lives here is the full panel: what the tool does, why this one stopped, what the
agent wrote, what yes and no each mean.

## The tokens

`web/src/tokens.css` is the page's `:root` blocks **ported verbatim** — 25 dark, 23 light, 4 motion
durations. Data, not code: these ramps were measured, and one of them exists because a dark pricing
band shipped at 1.16:1. `tests/test_console_tokens.py` fails if a value drifts from the page, in
either theme, and if any component writes a colour instead of a token.
