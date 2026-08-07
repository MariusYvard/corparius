<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/banner-dark.svg">
    <img src="docs/banner.svg" alt="corparius — self-hosted autonomous AI micro-companies you run yourself" width="100%">
  </picture>
</p>

<p align="center">
  <a href="https://github.com/MariusYvard/corparius/actions/workflows/ci.yml"><img src="https://img.shields.io/github/actions/workflow/status/MariusYvard/corparius/ci.yml?branch=main&style=flat-square&label=CI&labelColor=0A1D48" alt="CI"></a>
  <img src="https://img.shields.io/badge/python-3.10+-2456D3?style=flat-square&labelColor=0A1D48&logo=python&logoColor=white" alt="Python 3.10+">
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-2456D3?style=flat-square&labelColor=0A1D48" alt="MIT"></a>
  <img src="https://img.shields.io/badge/self--hosted-first-537CD6?style=flat-square&labelColor=0A1D48" alt="Self-hosted first">
  <img src="https://img.shields.io/badge/runs-offline%2C%20no%20keys-64B8D2?style=flat-square&labelColor=0A1D48" alt="Runs offline, no keys">
</p>

# corparius

Describe a business in plain language; corparius runs it as a set of scheduled
cognitive agents — a CEO plus nine operational roles — that pursue one signal,
revenue, while a budget and loop firewall stops them running away.

It is the local-first answer to hosted platforms like NanoCorp and Polsia: the
company config, the runtime state and the models stay on your own machine. Cloud
LLMs are an opt-in escalation, never a requirement. Ship nothing you cannot audit.

> Status: working MVP. The orchestrator, the safety firewall, the human-in-the-loop
> gate, the operator console and the ten-agent roster run end to end against a
> deterministic mock LLM, so you can watch a full company day with no network and
> no API keys. Live providers (Ollama, Anthropic, 14 free tiers, Claude Code CLI,
> any OpenAI-compatible gateway) are wired in and selected by config, and
> `corparius preflight` proves by one real call which of them your account can
> actually reach — a catalogue lists models that exist, not models you may call.

## Contents

[How it works](#how-it-works) ·
[The roster](#the-roster) ·
[Quick start](#quick-start) ·
[Operator console](#operator-console) ·
[LLM routing](#llm-routing) ·
[Safety firewall](#safety-firewall) ·
[Human in the loop](#human-in-the-loop) ·
[Compliance](#compliance-france--eu) ·
[Project layout](#project-layout) ·
[Plugins](#plugins) ·
[Skills](#skills) ·
[Documents](#documents) ·
[Company apps](#company-apps) ·
[Documentation](#documentation) ·
[Support](#support) ·
[Contributing](#contributing) ·
[License](#license)

## How it works

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/readme/pipeline-dark.svg">
    <img src="docs/readme/pipeline.svg" alt="One tick: company.yaml feeds the Scheduler, which picks the agents due; each Agent turn routes through the HybridRouter (local first, cloud on escalation); Tool calls are guarded by TokenBudget, LoopGuard and CircuitBreaker; money and production code wait at the human gate; everything lands in the SQLite store; and the CLI, operator console and MCP server read it back." width="100%">
  </picture>
</p>

Each agent runs on its own cadence (the CEO twice a day, outreach every three
hours, and so on). A tick advances the clock, runs whatever is due, records every
action and token, and stops the moment a guard trips.

## The roster

Ten roles, each with a fixed cadence and a narrow toolset. Cadences are staggered
so the company does not spend its whole budget in one burst.

| Agent | Cadence | Does |
| --- | --- | --- |
| CEO (orchestrator) | twice a day | Owns the backlog: creates and arbitrates tasks, sets the plan, writes the EOD summary |
| Social media | every 2h | Drafts and schedules posts for X and LinkedIn |
| Outreach | every 3h | Finds targets, sends cold email, tracks who replied |
| Support | every 3h | Triages the inbox, drafts replies |
| Ads | every 6h | Tracks ad budgets, writes variants, adjusts bids |
| Finance | every 6h | Reconciles Stripe flows, tracks spend, computes the balance |
| Strategy | daily | Reads KPIs, adjusts pricing, updates the roadmap |
| Competitor | daily | Web research, updates competitor profiles |
| Design | daily | Visual direction, brand consistency, builds the sales site |
| Coder | on demand | Builds features, fixes bugs, opens pull requests |

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/readme/rule-dark.svg">
    <img src="docs/readme/rule.svg" alt="" width="100%">
  </picture>
</p>

## Quick start

Runs offline out of the box (mock LLM, SQLite). No keys, no models, no accounts.

**No Python, no terminal, no clone — download one file and open it.** Grab the
build for your system from the [latest release](https://github.com/MariusYvard/corparius/releases/latest):

| System | Download | Then |
| --- | --- | --- |
| Windows x64 | `corparius-windows-x64.exe` | double-click (SmartScreen: More info → Run anyway) |
| macOS (Apple Silicon) | `corparius-macos-arm64.zip` | unzip, then right-click `corparius.app` → Open |
| macOS (Intel, 15+) | `corparius-macos-x64.zip` | unzip, then right-click `corparius.app` → Open |
| Linux x64 | `corparius-linux-x64` | `chmod +x corparius-linux-x64 && ./corparius-linux-x64` |

The builds are unsigned, so the OS shows a first-run warning; the steps above get
past it, and [docs/install.md](docs/install.md) walks through it with the exact
screens, where your data lives per OS, updating and uninstalling. Your data lives
in a per-OS folder, so re-downloading a newer build keeps every company and setting.

Prefer to run from source? Download the project, then **double-click the launcher
for your system** (needs Python 3.10+ installed):

| System | Double-click |
| --- | --- |
| Windows | `start-windows.bat` |
| macOS | `start-macos.command` (first time: right-click, Open) |
| Linux | `start-linux.sh` |

It sets up a virtualenv, installs the dependencies, prepares the example company,
opens the console in your browser, and tells you plainly if Python is missing.
The only prerequisite is Python 3.10+.

Prefer a terminal, or Docker:

```bash
git clone https://github.com/MariusYvard/corparius.git && cd corparius
python start.py        # venv, dependencies, .env, example company, console, browser
```

```bash
docker compose up -d   # operator console on http://127.0.0.1:8600 + local Ollama
```

Or pull the published image — no checkout, one command (console on
`http://127.0.0.1:8600`, offline mock mode, bound to localhost):

```bash
docker run -d -p 127.0.0.1:8600:8600 -v corparius_data:/app/data ghcr.io/mariusyvard/corparius
```

The console walks you through creating your first company; `python -m corparius.cli
doctor` diagnoses the installation and says what to fix. Compose profiles:
`--profile loop` adds the background company loop, `--profile extras` adds
Postgres and n8n.

The CLI covers everything the console does, and `corparius <command> --help`
explains each one:

| | |
| --- | --- |
| Run a company | `init` `run` `status` `board` `flow` `tasks` `task` |
| Decide | `approvals` `approve` `reject` `rules` `inbox` `memory` |
| Ship | `site` `deploy` `repo` `apps` |
| Models | `bench` `preflight` `claude` |
| Extend | `plugin` `skills` |
| Keep it running | `doctor` `ui` `set` `backup` `restore` `update` `secrets` |

## Operator console

`python -m corparius.cli ui` serves a zero-dependency web console on
`http://127.0.0.1:8600` (Python standard library only, single HTML file, dark
and light themes).

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/screenshots/console-dark.png">
    <img src="docs/screenshots/console.png" alt="corparius operator console: the count of decisions waiting on you in display scale, then recent agent activity, spend per agent in tokens, payments, task progress and lean flow metrics" width="100%">
  </picture>
</p>

The interface leads with what needs you: a status band puts the count of decisions
waiting on your approval in display scale, warm and unmissable, above everything
else, and the daily detail sits below it as a bento of varied cards rather than a
stack of identical boxes. Below the band, per company: lean flow metrics with the
current bottleneck, per-agent spend, the action log, the approval queue with
inline approve and reject, the CEO-governed backlog as a kanban you can arbitrate
and edit in place, run control (a burst of ticks or a loop you can stop), the
sales site with a headline and a publish button, backups, and a chat with the CEO
agent (given a face and a set of one-click openers) that answers from live company
state. A Documents tab holds what the company knows in files — drag one in, read
what the agents actually see of it, take one back out. The console is in English
and French, both tables carrying the same keys.

Nothing here needs a text editor. The company editor covers every field of the
company config; Settings covers everything corparius reads, from provider keys to
the mail account, Stripe, publishing targets, lead sources and the safety
ceilings. Connecting a mailbox is three answers: pick your provider, give the
address and an app password, then press Test and watch it send and read for real.

The console binds to localhost. Keys posted from the page are write-only: stored,
never displayed back, reported only as a `configured` boolean. Set `CORP_UI_TOKEN`
to require a header on every mutating call if you put it behind a reverse proxy.
Details in `docs/console.md`.

### Where settings live

Every setting resolves through four layers, first hit wins:

| Layer | Source | Set it from |
| --- | --- | --- |
| 1 | the real process environment | your shell, systemd, docker `environment:` |
| 2 | the settings saved from the console | the console |
| 3 | `.env` | a text editor |
| 4 | the default in the code | — |

The console can set everything in layer 2, and it says which layer answers for
each field: a value pinned by the process environment is shown read-only rather
than accepting an edit that would do nothing. Bootstrap keys (`CORP_DATA_PATH`,
`CORP_LOG_LEVEL`, `CORP_UI_HOST`, `CORP_UI_PORT`, `CORP_UI_TOKEN`) have to be
readable before the database opens, so they live in `.env` and apply on restart.

`.env` is read by corparius itself, not injected into the environment — which is
why `docker-compose.yml` mounts it instead of using `env_file:`.

Keys saved from the console land in `data/corparius.sqlite`, in the clear by
default (as they were in `.env` before), which the panel and the doctor both say.
Set a passphrase and they are encrypted at rest:

```bash
corparius secrets on      # encrypts the keys already stored, then new ones
corparius secrets status
```

`CORP_SECRET_KEY` is the passphrase and is a bootstrap key, so it lives in `.env`
or the process environment — never in the database it protects. A backup zip never
carries a plaintext secret either way: encrypted values ride along as ciphertext,
and unencrypted ones are blanked with `REDACTED.txt` naming what to re-enter.

## LLM routing

Three difficulty tiers, each mapped to a `<target>:<model>` string in `.env`.
Flip a prefix to move a tier between providers; keep any tier fully on-prem.

| Target | Serves | Needs |
| --- | --- | --- |
| `local:` | Ollama on your machine | nothing but the model |
| `cloud:` | Anthropic API | `ANTHROPIC_API_KEY` (paid credits) |
| `claudecode:` | Claude Code CLI, subscription auth | the CLI logged in, no API credits |
| `groq:` `cerebras:` `openrouter:` `mistral:` `gemini:` `nvidia:` `github:` `cohere:` `huggingface:` `ovh:` `zhipu:` `siliconflow:` `cloudflare:` `alibaba:` | 14 OpenAI-compatible providers on a free tier or a free trial quota | one API key each, free |
| `openai:` | OpenAI, OpenAI-compatible | `OPENAI_API_KEY` (billed from the first call) |
| `custom:` | any OpenAI-compatible gateway (OmniRoute, LiteLLM, vLLM, LM Studio) | `CORP_CUSTOM_LLM_URL` |

```bash
CORP_TRIVIAL_MODEL=local:gemma4:e4b
CORP_NORMAL_MODEL=groq:llama-3.3-70b-versatile
CORP_HARD_MODEL=openrouter:deepseek/deepseek-r1-0528:free
CORP_LLM_FALLBACK=cerebras:gpt-oss-120b,mistral:mistral-small-latest
```

When a remote call fails (rate limit, outage), the router walks the
`CORP_LLM_FALLBACK` chain in order; local Ollama always ends the chain, so the
company keeps working offline. A provider that refuses goes to the end of the
chain rather than being dropped, and comes back once it is rested. Free-tier
limits, signup links and privacy notes per provider: `docs/llm-providers.md`.

### Measured, not declared

A provider's catalogue lists models that exist, not models your account may call,
and a model card that advertises structured output is not proof that the model can
produce JSON. `corparius preflight` settles it with one real 8-token call per
model and stores the verdict:

```bash
corparius preflight                       # the models your tiers and fallback name
corparius preflight --provider openrouter # sweep a whole catalogue
```

Measured on a real key: **10 of 18 sampled NVIDIA catalogue entries answer 404**,
and **two of four models in a working fallback chain cannot produce JSON**. The
recommended routing refuses to pick a model measured dead, verdicts age so a
provider blocked six months ago gets another chance, and the console has the same
thing behind a button. `docs/llm-providers.md` carries the per-model table.

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/readme/rule-dark.svg">
    <img src="docs/readme/rule.svg" alt="" width="100%">
  </picture>
</p>

## Safety firewall

An autonomous agent left alone with an API and a credit card is a runaway-cost
incident waiting to happen. Three guards sit in front of every turn:

- `TokenBudget` is a hard per-session ceiling, checked before each call and
  updated after. Once spent, the agent halts and the operator is notified.
- `LoopGuard` catches semantic stutter. If the cosine similarity between the
  last outputs stays above the threshold across successive turns, or the same tool
  is called with identical parameters too many times, the turn is suspended.
- `CircuitBreaker` watches spend velocity. A sustained burst past the limit trips
  the breaker into a conservative, then safe, mode; safe mode freezes the session.

See `docs/securite.md` for the model and thresholds.

## Human in the loop

Some actions never run unattended. Any tool named in `CORP_HITL_TOOLS`
(`send_financial_transaction`, `publish_production_code` and `deploy_site` by
default) pauses the run and files an approval request with the full tool name and
parameters. Approve or reject from the console, the CLI or the MCP server. A
rejection is handed back to the agent as a normal, recoverable tool error.

## Compliance (France / EU)

Self-hosting the operations does not exempt the business from the law. `docs/`
covers the parts that bite: e-invoicing through an approved PDP (Factur-X, the
2027 B2B mandate), ten-year archival, the choice of legal form, and where the EU
AI Act classifies an agent as high-risk. Read `docs/conformite-fr.md` before you
point this at real customers.

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/readme/rule-dark.svg">
    <img src="docs/readme/rule.svg" alt="" width="100%">
  </picture>
</p>

## Project layout

```
corparius/
  cfg.py           settings resolver: environment > console > .env > default
  config.py        env-driven settings (dataclass, CORP_ prefix)
  settings_spec.py the registry of settings the console may write (one row each)
  company.py       the company config: one loader, one validator, one writer
  paths.py         where things live on disk
  models.py        typed records: agents, actions, approvals, LLM results
  llm.py           HybridRouter + Ollama, Anthropic, 14 free OpenAI-compatible
                   providers, OpenAI, Claude Code CLI and Mock
  safety.py        TokenBudget, LoopGuard, CircuitBreaker
  permissions.py   what a role may call, and what waits for you
  tools.py         the business toolbox, with HITL flags
  documents.py     the company's own files: extraction, prompt budget, writing
  mailbox.py       IMAP reading, read-only: support triage and prospect replies
  inbox.py         what an agent asks you, and what you answer
  structured.py    provider-agnostic output harness: same shape, whatever model
  claudecli.py     one-press Claude subscription setup (claudecode: target)
  provider_check.py test any provider with one real minimal call
  preflight.py     prove by a real 8-token call what an account can call
  modelinfo.py     the provider catalogues, cached; never dialled from a poll
  hardware.py      what this machine can run locally, measured
  ollama_setup.py  Ollama status and background model pulls from the console
  secretbox.py     encrypt the stored keys at rest (CORP_SECRET_KEY)
  backup.py        zip the store and the company configs
  selfupdate.py    replace this build with the newest release
  doctor.py        diagnose the installation and say what to fix
  i18n.py          the console and the agents in English or French
  sitegen.py       single-file sales-page generator
  deploy.py        interchangeable deploy providers (local, Netlify, S3, SSH)
  leadsource.py    interchangeable lead sources (local dataset, headless browser)
  enrich.py        lead enrichment providers (local heuristic, API-ready)
  deliverability.py outreach guard (suppression list, daily cap / warmup)
  signals.py       buying-signal watcher (local feed, headless browser)
  agents.py        the ten-agent roster + the turn executor
  skills.py        what the company knows, in prose (SKILL.md)
  plugins.py       the curated registry, install and load
  apps.py          the company's own LLM apps (+ appserver, appexport, appcli)
  companyrepo.py   give a company its own git repository
  hitl.py          approval gate and queue
  orchestrator.py  scheduler (cadences) + runtime (the tick loop)
  store.py         SQLite persistence
  webui.py         operator console server (stdlib HTTP, JSON API)
  webui.html       operator console page (single file, no build step)
  cli.py           init / run / status / tasks / board / flow / site / deploy / ui
  mcp_server.py    optional MCP server (drive corparius from an MCP host)
companies/example/ a sample company config, its skills, apps and documents
docs/              architecture, safety, compliance, and the RE dossier
tests/             guards, routing, backlog, console, settings layering, pipeline
```

## Plugins

corparius is extensible through plugins that add LLM/deploy/lead/enrich providers,
tools, company templates, or tweak an agent — without touching the core. They are
**off by default** and curated: a plugin is verified when it is in the reviewed
`plugins/registry.json`, and unverified third-party code loads only behind an
explicit opt-in. Install a verified plugin from the console (Plugins tab) or the
CLI:

```bash
corparius plugin list
corparius plugin install <name>     # downloads at a pinned ref, verifies the SHA-256
```

Write one from [`packaging/plugin-template/`](packaging/plugin-template/), then
propose it by opening a PR that adds it to `plugins/registry.json` — CI validates
and loads it. Full guide: [`docs/plugins.md`](docs/plugins.md).

## Skills

Plugins extend corparius with code. **Skills** extend it with what your company
knows — the objection your market actually raises, the price you never discount
below, the two words your founder refuses to see in a post. A skill is a
`SKILL.md` folder with YAML frontmatter; prose, not code, and nothing in it is
executed.

```
companies/<slug>/skills/<name>/SKILL.md   one company
skills/<name>/SKILL.md                    every company on this machine
```

`allowed-tools` in the frontmatter decides everything: the body is read into the
prompt only when the tool about to run is one it names, so a turn pays for the
skills that apply to it and nothing else. Start from
[`packaging/skill-template/`](packaging/skill-template/); the example company
ships one. Full guide: [`docs/skills.md`](docs/skills.md).

## Documents

Skills are what the company knows in prose. **Documents** are what it already has
in files: the pitch deck, the spec, the price list, a screenshot of a competitor's
page. Drop them in the Documents tab — or straight into the folder — and the text
becomes context its agents can use.

```
companies/<slug>/documents/            what you dropped in
companies/<slug>/documents/written/    what its agents wrote
```

**No new dependency.** A PDF, a `.docx`, a `.pptx`, an `.xlsx`, a CSV, a Markdown
note and a plain text file are all read with the standard library. **And nothing
is invented**: a scanned PDF answers "no text layer this build can read" rather
than returning noise, and a format with no extractor is named rather than guessed.
Nothing is uploaded anywhere — extraction happens in your process, and what
reaches a provider is what you put there.

**A picture is sent, not described.** No text is invented for an image, because
describing one needs a model that can see it — so the file itself travels, base64
in the provider's own dialect, still with no new dependency. It goes only where it
will be read: the tool has to have asked for it (a design brief and a competitor
scan do; reconciling Stripe does not) and the model has to be able to read one.
Which models can is **measured, not believed** — `corparius preflight` sends a
real two-colour test image and stores the verdict, and that verdict outranks the
catalogue's claim. Measured on a real key, on the three free models the catalogue
says take images: **one reads a picture, one claims it and cannot, one gave no
answer at all** — and that last one is recorded as "never proved", not as "blind".

`CORP_IMAGE_MAX_PER_CALL` bounds it, and **0 sends none, ever**. A document's text
is extracted on your machine; a picture has to leave it to be read, and a
screenshot may hold a customer's data. Turning every cloud provider off was the
only refusal available before — and that gives up the text too.

The agents write here too, which is the half that is easy to miss: a design brief,
a competitor scan, a pricing note and the end-of-day summary used to be produced,
logged as 120 characters, and thrown away. They are documents now, so the design
agent can read on Tuesday what it decided on Monday — and so can you.

**The console says which ones an agent actually reads.** The prompt block is
bounded, so a company holding twelve documents can be feeding two of them to its
agents. Each row carries its state: reaches the agents, reaches them truncated at
*n* of *m* characters, or on file and past the budget — that last one being the
thing nothing used to say out loud. Full guide:
[`docs/documents.md`](docs/documents.md).

## Company apps

The providers corparius already talks to, used for something other than the
roster: a FAQ on the sales site, a form that understands what a visitor wrote.
An app is a YAML file in `companies/<slug>/apps/` carrying its own token
ceiling, rate limit and origin list, and its spend shows up in the console under
`app:<name>`. No second API key, and none copied into a web page.

It runs in two places from one definition: baked into the static site at build
time, or on request through `corparius apps serve` (off by default, bound to
127.0.0.1, published with a tunnel). Full guide: [`docs/apps.md`](docs/apps.md).

## Documentation

| Doc | Covers |
| --- | --- |
| `docs/architecture.md` | orchestration topology, tiered router, durable execution |
| `docs/architecture-code.md` | the code's own structure: seven directories, five ranks, and the test that enforces the rule |
| `docs/adr/` | architecture decisions, one per file, each carrying the measurement behind it |
| `docs/console.md` | the operator console (API, security model) |
| `docs/llm-providers.md` | every free LLM provider: limits, keys, privacy notes |
| `docs/securite.md` | the safety firewall and the Agent SRE mapping |
| `docs/conformite-fr.md` | e-invoicing (PDP, Factur-X), legal forms, EU AI Act |
| `docs/backlog.md` | the CEO-governed task backlog |
| `docs/lean.md` | pull flow, WIP limits, flow metrics, kaizen |
| `docs/integrations.md` | the real-or-mock backend pattern (Stripe, SMTP) |
| `docs/site.md` `docs/deploiement.md` | sales-site generator and multi-provider publishing |
| `docs/leads.md` `docs/pipeline.md` | lead research, enrichment, deliverability, signals |
| `docs/mcp.md` | driving corparius from any MCP host |
| `docs/plugins.md` | writing, installing and proposing plugins |
| `docs/skills.md` | teaching a company its trade in prose (SKILL.md) |
| `docs/documents.md` | the company's own files: what is read, and what reaches a prompt |
| `docs/apps.md` | the company's own apps on its own providers |
| `docs/memoire.md` | yesterday vs what stays true: durable memory |
| `docs/install.md` | download/run per OS, data locations, updates |
| `docs/versionnement.md` | how a version is decided, stamped and released |
| `docs/roadmap-90j.md` | the 90-day build cycle |
| `docs/reverse-engineering/` | teardowns of NanoCorp, Polsia, Uclic, OpenWorker and knowledge-work-plugins |

## Support

corparius is free, MIT-licensed and self-hosted; there is no paid tier and no
telemetry. If it earns its keep in your homelab, you can support the work
through [GitHub Sponsors](https://github.com/sponsors/MariusYvard).

## Contributing

Issues and pull requests are welcome. Keep changes surgical, match the existing
conventions (dataclass config, provider registries with a local fallback, mock
mode must keep working offline) and make sure `python -m pytest` stays green.
New providers belong in the `OPENAI_COMPAT_PROVIDERS` registry with a
documentation row in `docs/llm-providers.md`.

## License

MIT. See [LICENSE](LICENSE).

Reference implementation for research and self-hosting. Autonomous outreach,
billing and publishing carry legal and reputational risk; you are the operator
and the agent acts on your behalf. Keep the HITL gate on anything that spends
money or ships code.
