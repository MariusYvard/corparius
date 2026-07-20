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

# CLI model aliases, so the tiers track the latest release instead of pinning a
# dated id. Trivial work goes to the cheapest, everyday and hard work to Sonnet.
TIERS = {
    "CORP_TRIVIAL_MODEL": "claudecode:haiku",
    "CORP_NORMAL_MODEL": "claudecode:sonnet",
    "CORP_HARD_MODEL": "claudecode:sonnet",
}

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


def plan() -> dict:
    """What the one-press setup would write, for a preview and for the payload."""
    return {**TOGGLES, **TIERS}


def already_on() -> bool:
    return (
        cfg.get_bool("CORP_CLAUDE_CODE")
        and cfg.get_bool("CORP_CLOUD_ENABLED")
        and not cfg.get_bool("CORP_LLM_MOCK", "true")
        and any(cfg.get(k, "").startswith("claudecode:") for k in TIERS)
    )
