"""Which model a tier is pointed at, and the vocabulary of the evidence that decides it.

Rank 3. Policy over measurements, and the last import cycle in the package died here.

`llm` asked `preflight` for `rank`, `claudecli` asked `llm` for `recommended_routing`, and
`llm` asked `claudecli` back — {claudecli, llm, preflight}, the fifth and last of the cycles
the restructuring started with. Neither function is provider code. `rank` takes candidates, a
tier, a catalogue and scores as parameters and does no I/O at all; `recommended_routing` reads
a provider table and a set of measurements and returns environment variables to write. Both
are decisions, and they were living inside the things they decide about.

**Rank 3, not 4, and that is a departure from the plan** — which put this in
`domain/routing_policy.py`. `claudecli.setup` calls `recommended_routing`, and `claudecli` is
rank 3: a rank-4 home would have created an upward import and undone the zero this
restructuring had just reached. The plan's own rule outranks the plan's own folder guess.

The verdict states come with it, for the same reason `key_env` moved to `apps`: they are the
contract *between* the prober and the policy, and the policy is the side that must not import
the prober. `preflight` produces a verdict; this is what a verdict means.
"""

from __future__ import annotations

import logging

from .config.provider_table import OPENAI_COMPAT_PROVIDERS

log = logging.getLogger("corparius.routing")

# The vocabulary of a probe verdict. Read by cli, doctor, hitl, preflight and webui — six
# modules sharing four strings, which is why they belong to none of them in particular.
USABLE = "usable"
BLOCKED = "blocked"
CAPACITY = "capacity"
UNKNOWN = "unknown"

# Preference for the general tiers: fast, generous models first; OpenRouter last
# for the normal tier because its default is a reasoning model (slower), but
# first choice for the hard tier for the same reason.
_ROUTING_ORDER = ["groq", "cerebras", "mistral", "ovh", "openrouter"]


def recommended_routing(
    configured: list[str],
    local_trivial: str = "",
    hard: str = "",
    fallback_tail=(),
    proven: dict[str, dict[str, dict]] | None = None,
    catalogue: dict[str, dict] | None = None,
    scores: dict[str, float] | None = None,
) -> dict[str, str] | None:
    """A coherent tier configuration from the free providers actually connected,
    so no tier resolves to something the operator has not set up.

    Returns the environment variables to write, or None when nothing usable is
    connected. This closes the gap left by the defaults (trivial on a local model
    that may be absent, normal/hard on paid Anthropic): enabling one free key set
    only the normal tier and left the rest broken. Here every tier lands on a
    connected provider - a reasoning model on hard when OpenRouter is in the mix,
    fast general models elsewhere, local on trivial when Ollama is up - and the
    fallback chain lists the remaining providers (the router always ends on local
    after it).

    `hard` overrides the top tier — that is what lets a metered account (a Claude
    subscription, in practice) take the strategy and coder work while the free
    providers carry the rest.

    `local_trivial` is the local model to put on the trivial tier, or "" for
    none. It replaced an `ollama_ready` boolean, which asked the wrong question:
    a port answering says nothing about whether the machine can serve a tier.
    The caller measures (see corparius/hardware.py) and passes the answer.

    `fallback_tail` is the remote ladder walked once every free provider has
    failed, before the router drops to local. It is deliberately separate from
    `hard`: the chain is shared by *every* tier, so putting the top-tier model
    there would let a failed social post escalate to the most expensive model in
    the roster. Cheapest first — the everyday work degrades one rung at a time.

    `proven` is what a preflight actually measured, from
    `preflight.proven_map`. Without it this behaves exactly as before, on the
    `default_model` literals — which are strings frozen on the day they were
    written, and they rot: openrouter's pinned default stopped existing while
    its paid variant stayed, so "recommended" routing wrote a tier that 404s.
    With it, a default known to be blocked is never chosen, and the replacement
    is the fastest model that province actually answered on. Measuring 785
    models to populate a dropdown would have been a waste; this is what the
    measurement is for.
    """
    picks = [
        p
        for p in _ROUTING_ORDER
        if p in configured and OPENAI_COMPAT_PROVIDERS.get(p, {}).get("default_model")
    ]
    if not picks:
        return None

    def model(provider: str, tier: str = "normal") -> str:
        default = OPENAI_COMPAT_PROVIDERS[provider]["default_model"]
        known = (proven or {}).get(provider) or {}
        if not known or known.get(default, {}).get("state") != "blocked":
            # Nothing measured, or the default is fine. Never second-guess a
            # working default on the strength of a faster alternative: the
            # defaults are chosen for capability, not latency.
            return f"{provider}:{default}"
        # A plain call now. This was `from .preflight import rank` inside the function body,
        # deferred to dodge the cycle the two of them made — and they are in the same file.
        usable = rank(known, tier=tier, catalogue=catalogue, scores=scores)
        if not usable:
            log.warning(
                "%s: the pinned default %s is not callable with this key, and nothing else "
                "on it has been proved. Leaving it; run `corparius preflight --provider %s`.",
                provider,
                default,
                provider,
            )
            return f"{provider}:{default}"
        # Best measured model on that provider — schema-capable first, then
        # reliable, then fast. See preflight.rank for why that order.
        best = usable[0]
        log.info("%s: %s is not callable; routing to %s, which answered", provider, default, best)
        return f"{provider}:{best}"

    normal_p = picks[0]
    hard_p = "openrouter" if "openrouter" in picks else normal_p
    # The chain is walked by every tier, so it is ranked as `normal`.
    chain = [model(p) for p in picks if p != normal_p]
    chain += [step for step in fallback_tail if step]
    return {
        "CORP_TRIVIAL_MODEL": (
            f"local:{local_trivial}" if local_trivial else model(normal_p, "trivial")
        ),
        "CORP_NORMAL_MODEL": model(normal_p, "normal"),
        "CORP_HARD_MODEL": hard or model(hard_p, "hard"),
        "CORP_LLM_FALLBACK": ",".join(chain),
    }


def rank(
    candidates: dict[str, dict],
    tier: str = "normal",
    catalogue: dict[str, dict] | None = None,
    scores: dict[str, float] | None = None,
) -> list[str]:
    """Models best-first for a given tier, on evidence, in order of authority.

    `candidates` is one provider's slice of `proven_map`. `catalogue` is
    `modelinfo.cached(...)` — what the provider says a model *is*. Without it
    this ranks on measurement alone, exactly as it did before.

    Two things always come first, whatever the tier, because they are not
    preferences:

    1. **Blocked is excluded.** It cannot be called at all.
    2. **JSON capability, where it was measured.** Every tool with a schema goes
       through `structured.ask`, so a model that cannot return a JSON object
       breaks most of the roster however capable it is on paper. Measured
       beats declared here and it is not close: `cerebras:gpt-oss-120b`
       advertises `structured_outputs` and was measured unable to do it. A
       model never *measured* is not penalised — absence of evidence is not
       evidence.
    3. **Reliability.** Two failures in five samples drops a turn in five.

    After that the tier decides, because the tiers want different things:

    - **hard** — strategy and code. Reasoning support, a large context and a
      recent generation matter more than speed; a slow model that thinks is the
      right trade for work that runs a few times a day.
    - **trivial** — a social post every two hours. Speed and a small model, and
      capability barely enters into it.
    - **normal** — capability and speed weighed together.

    An operator score (see `modelinfo.operator_scores`) outranks the derived
    signals when present, because someone who supplied one knows something this
    code does not.
    """
    catalogue = catalogue or {}
    tier = tier if tier in ("trivial", "normal", "hard") else "normal"
    usable = {m: v for m, v in candidates.items() if v.get("state") == USABLE}
    if not usable:
        return []

    def head(v):
        """What no tier trades away: it must follow a schema, and it must not
        drop turns."""
        measured = v.get("samples") or 0
        return (
            0 if (not measured or v.get("json_ok")) else 1,
            -round(v.get("reliability", 1.0) if measured else 1.0, 2),
        )

    def capability(model):
        info = _describe(model, catalogue, scores)
        # Recency stands in for generation: a 2026 model is a later generation
        # than a 2024 one, and the catalogue dates every entry it lists.
        return (
            info["score"] if info.get("score") is not None else 0.0,
            1 if info.get("reasoning") else 0,
            info.get("context") or 0,
            info.get("created") or 0.0,
            info.get("params_b") or 0.0,
        )

    def speed(v):
        return (-(v.get("tok_s") or 0.0), v.get("ms") or 10**6)

    if tier == "hard":
        # Strategy and code, a few times a day. A slow model that reasons is the
        # right trade; speed is the tiebreak, not the criterion.
        return sorted(
            usable,
            key=lambda m: (head(usable[m]), *[-x for x in capability(m)], *speed(usable[m]), m),
        )
    if tier == "trivial":
        # A social post every two hours. A 120B model here is paying for
        # capability nobody reads, so smaller wins ties.
        return sorted(
            usable,
            key=lambda m: (
                head(usable[m]),
                *speed(usable[m]),
                _describe(m, catalogue, scores).get("params_b") or 0.0,
                m,
            ),
        )

    # `normal` is the everyday work, and it is the one tier where neither axis
    # should dominate. A lexicographic key cannot express that — sorting by
    # speed first made `normal` identical to `trivial`, which is not a balance,
    # it is speed with extra steps. So: position in the speed ordering weighed
    # against position in the capability ordering.
    #
    # Speed counts double because this tier runs constantly, while capability
    # still moves a model up. An equal weighting was tried and is degenerate:
    # when the two orderings are exact opposites every model scores the same and
    # the result collapses to alphabetical.
    by_speed = sorted(usable, key=lambda m: (*speed(usable[m]), m))
    by_capability = sorted(usable, key=lambda m: (*[-x for x in capability(m)], m))
    place = {m: 2 * by_speed.index(m) + by_capability.index(m) for m in usable}
    return sorted(usable, key=lambda m: (head(usable[m]), place[m], m))


def _describe(model: str, catalogue: dict, scores: dict | None) -> dict:
    from . import modelinfo

    return modelinfo.describe(model, catalogue, scores)
