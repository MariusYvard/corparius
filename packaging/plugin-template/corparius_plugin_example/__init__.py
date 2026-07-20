"""Example corparius plugin.

Fork this directory, rename the package and the manifest `name`, and register
your own extensions in `register(api)`. corparius calls this hook once at startup
(when plugins are enabled) and hands you a PluginAPI; every method adds one entry
to a core registry. Nothing here reaches the network on import — the plugin only
declares what corparius can use.

The API (app/plugins.py PluginAPI):
  api.register_llm_provider(name, base, key_env, **opts)
  api.register_deploy_provider(provider)     # subclass app.deploy.DeployProvider
  api.register_lead_source(source)           # subclass app.leadsource.LeadSource
  api.register_enricher(enricher)            # subclass app.enrich.Enricher
  api.register_tool(tool)                    # app.tools.Tool (HITL + firewall apply)
  api.register_template(dict)                # a company template (see app.company.TEMPLATES)
  api.customize_agent(role, **overrides)     # tweak an existing agent's spec
"""

from __future__ import annotations

from app.deploy import DeployProvider


class ExampleDeployProvider(DeployProvider):
    """A bounded provider: `available()` decides whether the fallback chain uses
    it, `deploy()` does the work. This example is never available; flip the check
    and implement deploy() for a real target."""

    name = "example"

    def available(self) -> bool:
        return False

    def deploy(self, site_dir: str) -> str:
        return f"example:{site_dir}"


def register(api) -> None:
    # A free, OpenAI-compatible LLM provider is pure data: a base URL and the env
    # var that holds the key. It becomes selectable as "exampleai:<model>".
    api.register_llm_provider(
        "exampleai",
        base="https://api.example.com/v1",
        key_env="EXAMPLE_API_KEY",
    )
    api.register_deploy_provider(ExampleDeployProvider())
