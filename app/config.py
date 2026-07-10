"""Runtime configuration, read from environment variables (CORP_ prefix)."""
from __future__ import annotations
import os
import logging
from dataclasses import dataclass, field


def _csv(value: str) -> list[str]:
    return [v.strip() for v in value.split(",") if v.strip()]


def _bool(name: str, default: str = "false") -> bool:
    return os.environ.get(name, default).strip().lower() == "true"


@dataclass
class Settings:
    data_path: str = os.environ.get("CORP_DATA_PATH", "./data")
    log_level: str = os.environ.get("CORP_LOG_LEVEL", "INFO")

    # LLM routing (hybrid: local first, cloud on escalation).
    ollama_url: str = os.environ.get("CORP_OLLAMA_URL", "http://localhost:11434")
    # Model per routing tier, written as "local:<name>" or "cloud:<name>". Very
    # simple tasks run a tiny local model; normal and big tasks use cloud models
    # sized to the task. Change a prefix to keep any tier fully on-prem.
    trivial_model: str = os.environ.get("CORP_TRIVIAL_MODEL", "local:gemma4:e4b")
    normal_model: str = os.environ.get("CORP_NORMAL_MODEL", "cloud:claude-3-5-haiku-20241022")
    hard_model: str = os.environ.get("CORP_HARD_MODEL", "cloud:claude-3-5-sonnet-20241022")
    embed_model: str = os.environ.get("CORP_EMBED_MODEL", "nomic-embed-text")
    # Local model used as the fallback when a cloud tier is unreachable.
    local_model: str = os.environ.get("CORP_LOCAL_MODEL", "qwen2.5:7b-instruct")
    cloud_enabled: bool = _bool("CORP_CLOUD_ENABLED")
    anthropic_api_key: str = os.environ.get("ANTHROPIC_API_KEY", "")
    # Anthropic through the local Claude Code CLI (subscription auth, no API
    # credits). Enables the "claudecode:" target.
    claude_code_enabled: bool = _bool("CORP_CLAUDE_CODE")
    # Fallback chain: remote steps tried in order when a remote call fails,
    # e.g. "groq:llama-3.3-70b-versatile,cerebras:gpt-oss-120b". Local
    # (CORP_LOCAL_MODEL) always ends the chain. Free-provider API keys are
    # read straight from the environment by app/llm.py (one variable per
    # provider, see OPENAI_COMPAT_PROVIDERS and .env.example).
    llm_fallback: list[str] = field(
        default_factory=lambda: _csv(os.environ.get("CORP_LLM_FALLBACK", ""))
    )
    llm_mock: bool = _bool("CORP_LLM_MOCK", "true")

    # Safety budgets.
    session_token_budget: int = int(os.environ.get("CORP_SESSION_TOKEN_BUDGET", "100000"))
    tokens_per_minute_limit: int = int(os.environ.get("CORP_TOKENS_PER_MINUTE_LIMIT", "10000"))
    loop_similarity_threshold: float = float(os.environ.get("CORP_LOOP_SIMILARITY_THRESHOLD", "0.95"))
    max_identical_tool_calls: int = int(os.environ.get("CORP_MAX_IDENTICAL_TOOL_CALLS", "2"))

    # Human in the loop.
    hitl_tools: list[str] = field(
        default_factory=lambda: _csv(
            os.environ.get("CORP_HITL_TOOLS",
                           "send_financial_transaction,publish_production_code,deploy_site")
        )
    )


settings = Settings()


def setup_logging() -> None:
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )
