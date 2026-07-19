"""Smoke test for the example plugin. Run with corparius importable:
    pip install -e .        # or have the corparius source on PYTHONPATH
    pytest
CI for the corparius registry runs the equivalent load check on every proposed
plugin (see .github/workflows/plugins-validate.yml)."""
from app import deploy, llm, plugins

from corparius_plugin_example import register


def test_register_adds_its_extensions():
    api = plugins.PluginAPI()
    register(api)
    assert "exampleai" in llm.OPENAI_COMPAT_PROVIDERS
    assert "example" in deploy.REGISTRY
