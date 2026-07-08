"""Typed records shared across the runtime."""
from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class AgentRole(str, Enum):
    CEO = "ceo"
    SOCIAL = "social"
    OUTREACH = "outreach"
    SUPPORT = "support"
    ADS = "ads"
    FINANCE = "finance"
    STRATEGY = "strategy"
    COMPETITOR = "competitor"
    DESIGN = "design"
    CODER = "coder"


class Difficulty(str, Enum):
    """Routing tier for the HybridRouter. TRIVIAL runs a tiny local model
    (gemma4:e4b), EASY the default local model, HARD a task-adapted model that
    escalates to the cloud when enabled."""
    TRIVIAL = "trivial"
    EASY = "easy"
    HARD = "hard"


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def total(self) -> int:
        return self.input_tokens + self.output_tokens


@dataclass
class LLMResult:
    text: str
    usage: Usage
    model: str
    provider: str


@dataclass
class ToolResult:
    ok: bool
    output: str
    denied: bool = False    # rejected by a human approver
    pending: bool = False   # waiting on a human approver


@dataclass
class ApprovalRequest:
    id: str
    company: str
    agent: str
    tool: str
    parameters: dict[str, Any]
    status: str = "pending"   # pending | approved | rejected
    note: str = ""
    ts: float = 0.0
