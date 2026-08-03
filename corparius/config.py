"""Runtime configuration. Every field resolves through corparius/cfg.py, which reads
the process environment first, then the settings saved from the console, then
the .env file, then the default written here.

Fields use default_factory on purpose: a plain `os.environ.get(...)` default is
evaluated once, when the class is defined, so a second Settings() would hand
back the values the process started with and every console edit would look
inert. With default_factory, constructing Settings() re-resolves.

The module-level `settings` singleton below is still a snapshot taken at import.
That suits the CLI and the MCP server (one command, then exit) and the console
(which builds a fresh Settings() per request). The long-lived `run --loop`
process rebuilds it at each day boundary; see orchestrator.Runtime.run.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from . import cfg, paths, permissions


@dataclass
class Settings:
    data_path: str = field(
        default_factory=lambda: cfg.get("CORP_DATA_PATH", paths.default_data_dir())
    )
    log_level: str = field(default_factory=lambda: cfg.get("CORP_LOG_LEVEL", "INFO"))

    # LLM routing (hybrid: local first, cloud on escalation).
    ollama_url: str = field(
        default_factory=lambda: cfg.get("CORP_OLLAMA_URL", "http://localhost:11434")
    )
    # Local generations on CPU can take minutes; raise this rather than letting
    # runs die on slow hardware. Seconds.
    ollama_timeout: int = field(default_factory=lambda: cfg.get_int("CORP_OLLAMA_TIMEOUT", 420))
    # Model per routing tier, written as "local:<name>" or "cloud:<name>". Very
    # simple tasks run a tiny local model; normal and big tasks use cloud models
    # sized to the task. Change a prefix to keep any tier fully on-prem.
    trivial_model: str = field(
        default_factory=lambda: cfg.get("CORP_TRIVIAL_MODEL", "local:gemma4:e4b")
    )
    normal_model: str = field(
        default_factory=lambda: cfg.get("CORP_NORMAL_MODEL", "cloud:claude-3-5-haiku-20241022")
    )
    hard_model: str = field(
        default_factory=lambda: cfg.get("CORP_HARD_MODEL", "cloud:claude-3-5-sonnet-20241022")
    )
    # Local inference is only worth routing work to when the machine can serve
    # it. Below this measured throughput the trivial tier goes to a free
    # provider instead; see corparius/hardware.py.
    local_min_tokens_per_second: float = field(
        default_factory=lambda: cfg.get_float("CORP_LOCAL_MIN_TOKENS_PER_SEC", 15.0)
    )
    # How long a measurement stays trustworthy. A machine's speed does not
    # drift, but its free memory and its installed models do.
    bench_max_age_days: int = field(
        default_factory=lambda: cfg.get_int("CORP_BENCH_MAX_AGE_DAYS", 30)
    )
    embed_model: str = field(
        default_factory=lambda: cfg.get("CORP_EMBED_MODEL", "nomic-embed-text")
    )
    # Local model used as the fallback when a cloud tier is unreachable.
    local_model: str = field(
        default_factory=lambda: cfg.get("CORP_LOCAL_MODEL", "qwen2.5:7b-instruct")
    )
    cloud_enabled: bool = field(default_factory=lambda: cfg.get_bool("CORP_CLOUD_ENABLED"))
    anthropic_api_key: str = field(default_factory=lambda: cfg.get("ANTHROPIC_API_KEY", ""))
    # Anthropic through the local Claude Code CLI (subscription auth, no API
    # credits). Enables the "claudecode:" target.
    claude_code_enabled: bool = field(default_factory=lambda: cfg.get_bool("CORP_CLAUDE_CODE"))
    # Fallback chain: remote steps tried in order when a remote call fails,
    # e.g. "groq:llama-3.3-70b-versatile,cerebras:gpt-oss-120b". Local
    # (CORP_LOCAL_MODEL) always ends the chain. Free-provider API keys are
    # resolved by corparius/llm.py through the same layers (one variable per
    # provider, see OPENAI_COMPAT_PROVIDERS and .env.example).
    llm_fallback: list[str] = field(default_factory=lambda: cfg.get_csv("CORP_LLM_FALLBACK"))
    llm_mock: bool = field(default_factory=lambda: cfg.get_bool("CORP_LLM_MOCK", "true"))

    # Safety budgets.
    session_token_budget: int = field(
        default_factory=lambda: cfg.get_int("CORP_SESSION_TOKEN_BUDGET", 100000)
    )
    # A ceiling in the provider's own currency, applied only where a provider
    # reports a cost (OpenRouter does; most do not). 0 disables it, which is the
    # default: a second way for a run to stop has to be asked for.
    session_cost_budget: float = field(
        default_factory=lambda: cfg.get_float("CORP_SESSION_COST_BUDGET", 0.0)
    )
    tokens_per_minute_limit: int = field(
        default_factory=lambda: cfg.get_int("CORP_TOKENS_PER_MINUTE_LIMIT", 10000)
    )
    loop_similarity_threshold: float = field(
        default_factory=lambda: cfg.get_float("CORP_LOOP_SIMILARITY_THRESHOLD", 0.95)
    )
    max_identical_tool_calls: int = field(
        default_factory=lambda: cfg.get_int("CORP_MAX_IDENTICAL_TOOL_CALLS", 2)
    )

    # Operator console (corparius/webui.py). Binds to localhost; set CORP_UI_TOKEN
    # to require the X-Corp-Token header on every mutating call. These are
    # bootstrap keys (cfg.BOOTSTRAP): the console writes them to .env, and they
    # only take effect on restart.
    ui_host: str = field(default_factory=lambda: cfg.get("CORP_UI_HOST", "127.0.0.1"))
    ui_port: int = field(default_factory=lambda: cfg.get_int("CORP_UI_PORT", 8600))
    ui_token: str = field(default_factory=lambda: cfg.get("CORP_UI_TOKEN", ""))

    # Human in the loop. `hitl_tools` gates tools by name and outranks
    # everything else; the three below are the dials that decide what else has
    # to ask. See corparius/permissions.py for the resolution order.
    hitl_tools: list[str] = field(
        default_factory=lambda: cfg.get_csv(
            "CORP_HITL_TOOLS", "send_financial_transaction,publish_production_code,deploy_site"
        )
    )
    # discuss | interactive | auto | custom.
    permission_mode: str = field(
        default_factory=lambda: cfg.get("CORP_PERMISSION_MODE", permissions.INTERACTIVE)
    )
    # Ask for anything strictly above this risk class. The default (external)
    # plus the shipped hitl_tools is the behaviour corparius had before risk
    # classes existed, so upgrading changes nothing until the operator says so.
    ask_above: str = field(
        default_factory=lambda: cfg.get("CORP_ASK_ABOVE", permissions.DEFAULT_ASK_ABOVE)
    )
    # Auto-approved tool names. Honoured in `custom` mode only, so the list
    # cannot quietly loosen a stricter mode the operator picked on purpose.
    auto_allow: list[str] = field(default_factory=lambda: cfg.get_csv("CORP_AUTO_ALLOW"))

    # Skills: SKILL.md folders carrying what a company knows, in prose. On by
    # default, unlike plugins: this is text read into a prompt, not third-party
    # code executed in this process, so the supply-chain reason to be off does
    # not apply.
    skills_enabled: bool = field(
        default_factory=lambda: cfg.get_bool("CORP_SKILLS_ENABLED", "true")
    )
    # Ceiling on the instructions injected into one prompt, so a long note
    # cannot quietly become the largest line in the token budget.
    skill_max_chars: int = field(default_factory=lambda: cfg.get_int("CORP_SKILL_MAX_CHARS", 4000))

    # Durable memory. Separate from the three end-of-day summaries a run always
    # re-reads: those are yesterday, this is what stays true.
    memory_enabled: bool = field(
        default_factory=lambda: cfg.get_bool("CORP_MEMORY_ENABLED", "true")
    )
    # How many of the company's own pictures may ride on one model call. Zero is
    # the point of it being a setting at all: a document's text is extracted on
    # this machine, but a picture has to leave it to be read, and a screenshot may
    # hold a customer's data. Before this the only refusal available was turning
    # every cloud provider off, which also gives up the text.
    image_max_per_call: int = field(
        default_factory=lambda: cfg.get_int("CORP_IMAGE_MAX_PER_CALL", 2)
    )
    memory_top_k: int = field(default_factory=lambda: cfg.get_int("CORP_MEMORY_TOP_K", 5))
    # Ceiling on stored facts per company. Oldest unpinned are pruned first; a
    # pinned fact is the operator saying "this one stays" and is never pruned.
    memory_max: int = field(default_factory=lambda: cfg.get_int("CORP_MEMORY_MAX", 200))


settings = Settings()


def setup_logging() -> None:
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )
