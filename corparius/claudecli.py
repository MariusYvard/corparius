"""The Claude Code CLI as a subscription-backed provider.

`claudecode:` runs Anthropic models through the local `claude` CLI in headless
mode, using whatever login the CLI already holds. With a Claude subscription
that means no API credits and no key to paste. The catch is that it takes four
settings to turn on and the tiers have to be pointed at it by hand, so most
operators never find it. This module is the one-press path.

check() mirrors integrations.smtp_check: it proves the thing works rather than
asking the operator to trust it, by making one real, minimal call.
"""

from __future__ import annotations

import json
import shutil
import subprocess

from . import cfg, i18n

# CLI model aliases, not dated ids: the CLI resolves `haiku`, `sonnet` and
# `opus` to whatever the current release is, so the tiers track it without
# anything here to update. A ladder, one model per tier.
TIERS = {
    "CORP_TRIVIAL_MODEL": "claudecode:haiku",
    "CORP_NORMAL_MODEL": "claudecode:sonnet",
    "CORP_HARD_MODEL": "claudecode:opus",
}

# What the top tier gets when free providers carry the rest.
#
# Opus rather than Sonnet, and the cadence is what makes that affordable. HARD
# serves exactly two roles: strategy, every 24 hours, and the coder, on demand.
# It is the least frequent tier in the roster, so the model that costs the most
# per call is the one that gets called least — which is the whole point of
# having tiers. Put Opus on `normal` and a subscription window would go on
# drafting support replies.
HARD_TIER = "claudecode:opus"

# The last remote step of the fallback chain: where the everyday work goes once
# every free provider has failed, before the router drops to local.
#
# Sonnet, not Opus, and not because Sonnet is the mid tier by coincidence. The
# chain is shared by every tier, so whatever sits at its end is what a failed
# *social post* escalates to as readily as a failed strategy review. Opus there
# would turn a provider outage into the most expensive hour the company has
# ever run. Sonnet is what normal work should degrade to; Opus stays the hard
# tier's own model and is reached by being asked for, not by falling over.
NORMAL_FALLBACK = "claudecode:sonnet"

# Flipped on by the one-press setup. Cloud is the master gate for every remote
# provider, so it has to be on too; enabling Claude Code alone does nothing, and
# that hidden AND is most of why this was hard to turn on.
TOGGLES = {
    "CORP_LLM_MOCK": "false",
    "CORP_CLOUD_ENABLED": "true",
    "CORP_CLAUDE_CODE": "true",
}

INSTALL_EN = (
    "The `claude` CLI is not on this machine's PATH. Install Claude Code "
    "(claude.com/product/claude-code), then run `claude login` and pick "
    "your subscription."
)
INSTALL_FR = (
    "Le CLI `claude` n'est pas sur le PATH de cette machine. Installez "
    "Claude Code (claude.com/product/claude-code), puis lancez "
    "`claude login` et choisissez votre abonnement."
)


def resolve() -> str | None:
    """The full path to the CLI, with its extension.

    On Windows the CLI npm installs is `claude.cmd`, and subprocess cannot launch
    a .cmd by its bare name — it fails with WinError 2. Passing the resolved path
    works. Every caller must go through here, or `claudecode:` is silently broken
    on Windows.
    """
    return shutil.which("claude")


def installed() -> bool:
    return bool(resolve())


def check(timeout: int = 60, lang="en") -> dict:
    """Is the CLI installed, logged in and answering? Makes one real minimal
    call, the same bargain as the mail test: a subscription message is spent to
    prove the setup, because nothing cheaper actually proves it."""
    p = lambda en, fr: i18n.pick(lang, en, fr)
    exe = resolve()
    if not exe:
        return {"ok": False, "installed": False, "detail": p(INSTALL_EN, INSTALL_FR)}
    try:
        proc = subprocess.run(
            [exe, "-p", "Reply with the single word: ready", "--output-format", "json"],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return {
            "ok": False,
            "installed": True,
            "detail": p(
                f"The CLI did not answer within {timeout}s. It may be waiting "
                "on a login prompt; run `claude login` in a terminal once.",
                f"Le CLI n'a pas répondu en {timeout}s. Il attend peut-être une "
                "connexion ; lancez `claude login` une fois dans un terminal.",
            ),
        }
    except OSError as exc:
        return {
            "ok": False,
            "installed": True,
            "detail": p(f"Could not run the CLI: {exc}", f"Impossible de lancer le CLI : {exc}"),
        }
    if proc.returncode != 0:
        err = (proc.stderr or "").strip()
        low = err.lower()
        if any(w in low for w in ("login", "auth", "unauthor", "not logged", "credential")):
            return {
                "ok": False,
                "installed": True,
                "detail": p(
                    "The CLI is installed but not logged in. Run `claude login` "
                    "and choose your subscription, then test again.",
                    "Le CLI est installé mais non connecté. Lancez `claude login`, "
                    "choisissez votre abonnement, puis retestez.",
                ),
            }
        return {
            "ok": False,
            "installed": True,
            "detail": p(
                f"The CLI exited {proc.returncode}: {err[:200] or 'no output'}",
                f"Le CLI s'est arrêté ({proc.returncode}) : {err[:200] or 'aucune sortie'}",
            ),
        }
    try:
        data = json.loads(proc.stdout)
        model = data.get("model") or ""
    except (json.JSONDecodeError, AttributeError):
        model = ""
    return {
        "ok": True,
        "installed": True,
        "detail": p(
            "The Claude Code CLI is installed, logged in and answering. "
            "No API key or credits needed." + (f" Answering as {model}." if model else ""),
            "Le CLI Claude Code est installé, connecté et répond. Aucune clé API "
            "ni crédit requis." + (f" Répond en tant que {model}." if model else ""),
        ),
    }


def plan(configured=None, ollama_ready: bool = False, all_tiers: bool = False) -> dict:
    """What the one-press setup would write, for a preview and for the payload.

    A Claude subscription is metered in usage windows, not in tokens, so
    spending it on `draft_social_post` — TRIVIAL, every two hours — is the
    expensive mistake. When free providers are connected they take the trivial
    and normal tiers and Claude takes only HARD, which is strategy and the
    coder: the two roles where the difference is worth a window.

    Claude also becomes the last remote step of the fallback chain, so a free
    provider going down escalates to the subscription instead of dropping
    straight to a local model that may not be installed.

    With nothing free connected there is nothing to prefer, so Claude serves
    every tier — the behaviour this had before. `all_tiers` asks for that
    deliberately.
    """
    from .llm import recommended_routing

    if all_tiers:
        return {**TOGGLES, **TIERS}
    routing = recommended_routing(
        list(configured or []), ollama_ready, hard=HARD_TIER, fallback_tail=NORMAL_FALLBACK
    )
    if routing is None:
        return {**TOGGLES, **TIERS}
    return {**TOGGLES, **routing}


def already_on() -> bool:
    return (
        cfg.get_bool("CORP_CLAUDE_CODE")
        and cfg.get_bool("CORP_CLOUD_ENABLED")
        and not cfg.get_bool("CORP_LLM_MOCK", "true")
        and any(cfg.get(k, "").startswith("claudecode:") for k in TIERS)
    )
