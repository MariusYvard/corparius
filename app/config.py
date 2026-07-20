"""Runtime configuration. Every field resolves through app/cfg.py, which reads
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

from . import cfg, paths


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
    # resolved by app/llm.py through the same layers (one variable per
    # provider, see OPENAI_COMPAT_PROVIDERS and .env.example).
    llm_fallback: list[str] = field(default_factory=lambda: cfg.get_csv("CORP_LLM_FALLBACK"))
    llm_mock: bool = field(default_factory=lambda: cfg.get_bool("CORP_LLM_MOCK", "true"))

    # Safety budgets.
    session_token_budget: int = field(
        default_factory=lambda: cfg.get_int("CORP_SESSION_TOKEN_BUDGET", 100000)
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

    # Operator console (app/webui.py). Binds to localhost; set CORP_UI_TOKEN
    # to require the X-Corp-Token header on every mutating call. These are
    # bootstrap keys (cfg.BOOTSTRAP): the console writes them to .env, and they
    # only take effect on restart.
    ui_host: str = field(default_factory=lambda: cfg.get("CORP_UI_HOST", "127.0.0.1"))
    ui_port: int = field(default_factory=lambda: cfg.get_int("CORP_UI_PORT", 8600))
    ui_token: str = field(default_factory=lambda: cfg.get("CORP_UI_TOKEN", ""))

    # Human in the loop.
    hitl_tools: list[str] = field(
        default_factory=lambda: cfg.get_csv(
            "CORP_HITL_TOOLS", "send_financial_transaction,publish_production_code,deploy_site"
        )
    )


settings = Settings()


def setup_logging() -> None:
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )
