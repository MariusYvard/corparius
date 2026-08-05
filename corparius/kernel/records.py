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
    # What the provider says this call cost, in its own account currency, when
    # it says anything at all. Most do not: `cost` is 0.0 for them, and that
    # means "not reported", never "free". Anything displaying it has to keep
    # those two apart, or a paid run reads as costless.
    cost: float = 0.0
    # Local inference only: what Ollama timed for this call. Throughput is what
    # decides whether this machine can serve a tier at all, and it arrives in
    # every response — the same field-already-there miss as `cost`.
    tokens_per_second: float = 0.0
    load_seconds: float = 0.0

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
    denied: bool = False  # rejected by a human approver
    pending: bool = False  # waiting on a human approver
    # What this result is waiting on, so a backlog task can record which answer
    # would unblock it instead of being retried blindly every turn while the
    # operator has not responded. An approval answers "may I"; a question
    # answers "with what". Both park the work the same way.
    approval_id: str = ""
    question_id: str = ""


@dataclass
class ApprovalRequest:
    id: str
    company: str
    agent: str
    tool: str
    parameters: dict[str, Any]
    status: str = "pending"  # pending | approved | rejected
    note: str = ""
    ts: float = 0.0
    # Everything the operator needs to judge the request, and nothing the id is
    # hashed from. `parameters` is hashed, so the draft in it had to be cut to
    # 80 characters or the same request would look new on every tick — which
    # meant approving an outreach email nobody could read.
    detail: dict[str, Any] = field(default_factory=dict)
