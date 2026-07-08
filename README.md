# corparius

Self-hosted framework for autonomous AI micro-companies. You describe a business
in plain language; corparius runs it as a set of scheduled cognitive agents, a
CEO plus operational roles, that pursue a single signal (revenue) while a budget
and loop firewall stops them running away.

It is the local-first answer to hosted platforms like NanoCorp and Polsia: the
company config, the runtime state and the models stay on your own machine. Cloud
LLMs are an opt-in escalation, never a requirement. Ship nothing you cannot audit.

> Status: working MVP. The orchestrator, safety firewall, human-in-the-loop gate
> and the ten-agent roster runs end to end against a deterministic mock LLM, so
> you can watch a full company "day" with no network and no API keys. Real
> Ollama and Anthropic providers are wired in and selected by config.

## How it works

```
company.yaml  ->  Scheduler        picks the agents due this tick
                     |
                     v
                  Agent turn        system prompt + company state -> LLM
                     |                     (HybridRouter: local -> cloud)
                     v
                  Tool calls        guarded by the safety firewall
                     |                  - TokenBudget      (hard ceiling)
                     |                  - LoopGuard        (semantic stutter)
                     |                  - CircuitBreaker   (spend velocity)
                     v
                  HITL gate         money / prod code -> wait for a human
                     |
                     v
                  Store (SQLite)    actions, usage, approvals, KPIs
```

Each agent runs on its own cadence (the CEO twice a day, outreach every three
hours, and so on). A tick advances the clock, runs whatever is due, records every
action and token, and stops the moment a guard trips.

## The roster

Ten roles, each with a fixed cadence and a narrow toolset. Cadences are staggered
so the company does not spend its whole budget in one burst.

| Agent | Cadence | Does |
| --- | --- | --- |
| CEO (orchestrator) | twice a day | Sets the morning plan, arbitrates priorities, writes the end-of-day summary |
| Social media | every 2h | Drafts and schedules posts for X and LinkedIn |
| Outreach | every 3h | Finds targets from enriched data, sends cold email |
| Support | every 3h | Triages the inbox, drafts replies |
| Ads | every 6h | Tracks ad budgets, writes variants, adjusts bids |
| Finance | every 6h | Reconciles Stripe flows, tracks spend, computes the balance |
| Strategy | daily | Reads KPIs, adjusts pricing, updates the roadmap |
| Competitor | daily | Web research, updates competitor profiles |
| Design | daily | Visual direction, brand consistency, builds the sales site |
| Coder | on demand | Builds features, fixes bugs, opens pull requests |

## Quick start

Runs offline out of the box (mock LLM, SQLite). No keys, no models needed.

```bash
git clone <your-repo> corparius && cd corparius
python -m venv .venv && . .venv/Scripts/activate   # Windows
pip install -r requirements.txt
cp .env.example .env

python -m app.cli init --company companies/example/company.yaml
python -m app.cli run  --company example --ticks 6   # simulate a day
python -m app.cli status   --company example
python -m app.cli site     --company example         # build the sales page
python -m app.cli deploy   --company example         # publish it (local by default)
python -m app.cli approvals --company example        # pending human gates
```

To go live, set `CORP_LLM_MOCK=false` and start the self-hosted stack
(`docker compose up -d`). Routing is tiered: trivial work runs on a tiny local
model (`ollama pull gemma4:e4b`), while the normal and hard tiers point at cloud
models, so set `CORP_CLOUD_ENABLED=true` and `ANTHROPIC_API_KEY`. Each tier is a
`local:` / `cloud:` string in `.env`; flip a prefix to keep that tier on-prem.

## Safety firewall

An autonomous agent left alone with an API and a credit card is a runaway-cost
incident waiting to happen. Three guards sit in front of every turn:

- `TokenBudget` is a hard per-session ceiling, checked before each call and
  updated after. Once spent, the agent halts and Operations is notified.
- `LoopGuard` catches semantic stutter. If the cosine similarity between the
  last outputs stays above the threshold across successive turns, or the same tool
  is called with identical parameters too many times, the turn is suspended.
- `CircuitBreaker` watches spend velocity. Normal work stays under a few thousand
  tokens a minute, and a sustained burst past the limit trips the breaker into a
  conservative, then safe, mode.

See `docs/securite.md` for the model and thresholds.

## Human in the loop

Some actions never run unattended. Any tool named in `CORP_HITL_TOOLS`
(`send_financial_transaction` and `publish_production_code` by default) pauses the
run and files an approval request with the full tool name and parameters. Approve
or reject from the CLI (or wire it to n8n / Slack). A rejection is handed back to
the agent as a normal, recoverable tool error.

## Compliance (France / EU)

Self-hosting the operations does not exempt the business from the law. `docs/`
covers the parts that bite: e-invoicing through an approved PDP (Factur-X, the
2027 B2B mandate), ten-year archival, the choice of legal form, and where the EU
AI Act classifies an agent as high-risk. Read `docs/conformite-fr.md` before you
point this at real customers.

## Project layout

```
app/
  config.py        env-driven settings (dataclass, CORP_ prefix)
  models.py        typed records: agents, actions, approvals, LLM results
  llm.py           HybridRouter + Ollama, Anthropic and Mock providers
  safety.py        TokenBudget, LoopGuard, CircuitBreaker
  tools.py         the business toolbox, with HITL flags
  sitegen.py       single-file sales-page generator
  deploy.py        interchangeable deploy providers (local, Netlify, S3, SSH)
  leadsource.py    interchangeable lead sources (local dataset, headless browser)
  agents.py        the ten-agent roster + the turn executor
  hitl.py          approval gate and queue
  orchestrator.py  scheduler (cadences) + runtime (the tick loop)
  store.py         SQLite persistence
  cli.py           init / run / status / approvals / approve / reject
companies/example/ a sample company config
docs/              architecture, safety, compliance, and the RE dossier
tests/             guard and routing unit tests
```

## Docs

- `docs/architecture.md` covers the orchestration topology, the tiered router, durable execution and MCP.
- `docs/securite.md` covers the safety firewall, the Agent SRE mapping and human-in-the-loop.
- `docs/conformite-fr.md` covers e-invoicing (PDP and Factur-X), legal forms and the EU AI Act.
- `docs/roadmap-90j.md` covers the 90-day build cycle and the path to production.
- `docs/integrations.md` covers the real-or-mock backend pattern and the wired Stripe and SMTP integrations.
- `docs/site.md` covers the one-command sales-site generator.
- `docs/deploiement.md` covers multi-provider publishing (local, Netlify, S3, SSH) with fallback.
- `docs/leads.md` covers lead research (local dataset, headless browser) and the responsibility note.
- `docs/reverse-engineering/` holds teardowns of NanoCorp, Polsia and Uclic, plus a comparison.

## Disclaimer

Reference implementation for research and self-hosting. Autonomous outreach,
billing and publishing carry legal and reputational risk; you are the operator
and the agent acts on your behalf. Keep the HITL gate on anything that spends
money or ships code.
