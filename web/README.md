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

| Tab | State |
| --- | --- |
| Overview | done — what needs you, the pulse, the run |
| Operations | to do |
| Documents | to do |
| Providers | to do |
| CEO | to do |
| Settings | to do |

**Overview reads three v1 resources and writes to three more.** `summary` (2 859 bytes, polled),
`jobs` (the durable run), and `companies`; it posts to `approvals`, `inbox` and `runs`. Every one of
those writes moved to v1 *because this tab needed it* — the plan's "reads first, writes when a v1
client has a decision to make", and a v1 client now does.

## The tokens

`web/src/tokens.css` is the page's `:root` blocks **ported verbatim** — 25 dark, 23 light, 4 motion
durations. Data, not code: these ramps were measured, and one of them exists because a dark pricing
band shipped at 1.16:1. `tests/test_console_tokens.py` fails if a value drifts from the page, in
either theme, and if any component writes a colour instead of a token.
