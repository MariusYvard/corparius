"""What this installation is, and what it can actually do. Rank 5.

The first brick of the plan's stage 8, and the one a second client cannot do without. Two
things a thin client needs before it renders anything:

  * **the versions**, so it can refuse a core too old for it rather than failing one request at
    a time. Three of them, and they are not interchangeable: `api` is the contract, `app` is the
    build, `schema` is the store's own `PRAGMA user_version`.
  * **the capabilities**, so it hides a button instead of discovering a 404. That distinction is
    the whole point: an installation with no mail account configured has no "test mail" to
    offer, and a client that shows one is lying about what the operator has.

**Every capability is resolved from configuration, never declared.** This project's own rule —
measured beats declared — and here it is the difference between a client that works and one that
offers what the operator did not set up. `mail` is true when a provider is configured, not when
the feature exists in the code.

**And never by a network probe.** This is meant to be polled, and the rule against opening a
socket from a polled endpoint was written after `/api/providers` did exactly that on every
refresh. So `payments` asks whether a Stripe key is set, not whether Stripe answers — the first
draft of this file called `stripe_check()`, which reads the live balance. Whether a configured
thing *works* is `corparius doctor`'s question, and it is asked when an operator asks it.

`api_version` is `1` and will stay a small integer. A client compares it; nobody parses it.
"""

from __future__ import annotations

from .. import __version__
from ..config import cfg, settings_spec

API_VERSION = 1


def capabilities(settings, store=None) -> dict[str, bool]:
    """What this installation can do right now, asked of its configuration.

    Each answer is a fact about *this* machine and *these* settings. A client rendering from
    this shows only what the operator can actually reach — which is why nothing here reports
    whether the feature is implemented. That is what a version is for.
    """
    from ..providers import claudecli, mailbox
    from ..providers.llm import connected_providers

    return {
        # A model can answer at all: a remote provider with a key, the Claude CLI logged in, or
        # mock mode — which is a real capability, not the absence of one. It is how the product
        # runs offline on a first install.
        "models": bool(
            settings.llm_mock
            or connected_providers()
            or (settings.claude_code_enabled and claudecli.installed())
        ),
        "mail": mailbox.configured(),
        # A key is set. **Not** `stripe_check()`, which reads the live balance: this endpoint is
        # meant to be polled, and this project has a rule against a network probe from a polled
        # point — it was written after `/api/providers` opened a socket on every refresh. Whether
        # the key *works* is what `corparius doctor` is for.
        "payments": bool(cfg.get("STRIPE_API_KEY", "").strip()),
        "skills": bool(settings.skills_enabled),
        "memory": bool(settings.memory_enabled and settings.memory_top_k > 0),
        # Encryption at rest is opt-in and needs an optional package. "Asked for" and "possible"
        # are different, and a client offering to encrypt on a machine without `cryptography`
        # would be offering a RuntimeError.
        "secrets_at_rest": _secrets_ready(),
        "plugins": cfg.get_bool("CORP_PLUGINS_ENABLED"),
        # True since schema 19. A run is a row in `jobs`, so it survives a restart of the console
        # — and a run the console was holding when it died reads back as `interrupted` rather than
        # as silence. Which schema the store is actually at is `schema_version` in this same
        # payload, so a client that needs to be sure does not have to trust this flag alone.
        "durable_jobs": True,
    }


def _secrets_ready() -> bool:
    from ..config import secretbox

    return bool(secretbox.enabled() and secretbox.available())


def describe(settings, store=None) -> dict:
    """The whole answer. Cheap enough to be public: it names no secret and no company."""
    return {
        "api_version": API_VERSION,
        "app_version": __version__,
        # The store's own stamp, not a constant in the code. An upgrade migrates in place, so
        # what a client needs to know is what the *database* is at — and asking the constant
        # would report the version this build expects rather than the one it found.
        "schema_version": store.schema_version() if store is not None else None,
        "settings_count": len(settings_spec.BY_KEY),
        "capabilities": capabilities(settings, store),
    }
