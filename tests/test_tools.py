"""The toolbox is the surface where an agent turn touches the real world, and
two of its entries move money or ship production code. Nothing exercised those
bodies directly before: coverage came incidentally through a full run, so a tool
could break in a way no test named.

Every tool is driven here through the registry, offline. The mock effects and
the "return None when unconfigured" contract in app/integrations.py are what
make that possible without a network or a key.
"""
from app.models import ToolResult
from app.orchestrator import RunContext
from app.safety import CircuitBreaker, TokenBudget
from app.store import Store
from app.tools import TOOLS

# The tools the operator must approve by hand. This list is a claim about the
# product, not an implementation detail: if a tool moves money or touches
# production and drops off it, the HITL gate silently stops covering it.
GATED = {"send_financial_transaction", "publish_production_code", "deploy_site"}


def _company() -> dict:
    return {
        "slug": "t", "name": "T",
        "offer": {"product": "p"},
        "icp": {"segment": "seg", "channels": ["linkedin"], "pains": ["pain"]},
        "budgets": {"daily_ad_spend_eur": 10},
        "agents": {"social": True, "outreach": True, "support": True, "design": True},
    }


def _ctx(tmp_path) -> RunContext:
    store = Store(str(tmp_path / "data"))
    return RunContext(company=_company(), tick=0,
                      budget=TokenBudget(100000), breaker=CircuitBreaker(100000),
                      data_path=str(tmp_path / "data"), store=store)


def test_registry_is_keyed_by_its_own_names():
    """TOOLS is built by comprehension over _ALL, so a copy-pasted name would
    silently shadow another tool rather than raise."""
    for name, tool in TOOLS.items():
        assert tool.name == name


def test_every_tool_is_described_and_runnable():
    for name, tool in TOOLS.items():
        assert tool.description.strip(), f"{name} has no description"
        assert callable(tool._effect), f"{name} has no effect"
        if tool.needs_draft:
            assert tool._prompt is not None, f"{name} needs a draft but has no prompt"


def test_money_and_production_tools_are_gated():
    for name in GATED:
        assert name in TOOLS, f"{name} vanished from the toolbox"
        assert TOOLS[name].hitl is True, f"{name} is no longer behind the HITL gate"


def test_no_other_tool_claims_the_gate():
    """The inverse assertion: a tool marked hitl that nobody expects is a
    company that stalls every day waiting for an approval no one knows to give."""
    assert {n for n, t in TOOLS.items() if t.hitl} == GATED


def test_every_tool_runs_offline_and_returns_a_result(tmp_path):
    ctx = _ctx(tmp_path)
    for name, tool in TOOLS.items():
        result = tool.run(ctx, "draft text")
        assert isinstance(result, ToolResult), f"{name} returned {type(result)}"
        assert result.output.strip(), f"{name} returned an empty output"


def test_draft_prompts_render_without_a_model(tmp_path):
    """The prompt lambdas read company fields; a missing key would raise at the
    top of an agent turn, before any LLM call could report the problem."""
    ctx = _ctx(tmp_path)
    for name, tool in TOOLS.items():
        if tool.needs_draft:
            assert tool.draft_prompt(ctx).strip(), f"{name} rendered an empty prompt"


def test_deploy_publishes_locally_with_nothing_configured(tmp_path):
    """The local provider is always available on purpose, so the default first
    run publishes somewhere real rather than reporting a configuration error."""
    ctx = _ctx(tmp_path)
    result = TOOLS["deploy_site"].run(ctx, "")
    assert result.ok is True
    assert (tmp_path / "data" / "sites" / "published" / "index.html").is_file()


def test_deploy_fails_honestly_when_no_provider_is_available(tmp_path, monkeypatch):
    """deploy_result exists because deploy_site returns a string either way: a
    total failure used to come back looking exactly like a success and was
    logged as one. Drop the always-on local provider and the tool must say so."""
    monkeypatch.setenv("CORP_DEPLOY_PROVIDERS", "netlify,s3,ssh")
    ctx = _ctx(tmp_path)
    result = TOOLS["deploy_site"].run(ctx, "")
    assert result.ok is False
    assert "not published" in result.output


def test_ad_budget_reads_the_configured_cap(tmp_path):
    ctx = _ctx(tmp_path)
    assert "10 EUR/day" in TOOLS["review_ad_budget"].run(ctx, "").output
    ctx.company["budgets"]["daily_ad_spend_eur"] = 0
    assert "ads stay off" in TOOLS["review_ad_budget"].run(ctx, "").output


def test_social_post_uses_the_configured_channel(tmp_path):
    ctx = _ctx(tmp_path)
    ctx.company["icp"]["channels"] = ["x"]
    assert "for x:" in TOOLS["draft_social_post"].run(ctx, "").output


def test_site_build_ignores_a_mock_draft_as_a_headline(tmp_path):
    """Offline is the default first run, so feeding the echoed mock prompt in as
    the site's H1 would make the product look broken on day one."""
    ctx = _ctx(tmp_path)
    result = TOOLS["build_sales_site"].run(ctx, "[mock: write a headline]")
    assert result.ok
    index = (tmp_path / "data" / "sites" / "t" / "index.html").read_text(encoding="utf-8")
    assert "[mock:" not in index
