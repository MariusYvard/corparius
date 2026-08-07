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

from ..config import cfg
from ..kernel import i18n, proc

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

# The remote ladder walked once every free provider has failed, before the
# router drops to local. Cheapest rung first.
#
# Haiku comes before Sonnet because this chain is shared by every tier: what
# sits on it is what a failed *social post* escalates to as readily as a failed
# strategy review. A machine that cannot run local inference sends trivial work
# to a free provider, and when that goes down Haiku is the right next rung —
# Sonnet only if Haiku is down too.
#
# Opus is not on the ladder at all. It stays the hard tier's own model, reached
# because a HARD task asked for it, never because something else fell over.
# Putting it here would turn a provider outage into the most expensive hour the
# company has ever run.
FALLBACK_LADDER = ("claudecode:haiku", "claudecode:sonnet")

# Flipped on by the one-press setup. Cloud is the master gate for every remote
# provider, so it has to be on too; enabling Claude Code alone does nothing, and
# that hidden AND is most of why this was hard to turn on.
TOGGLES = {
    "CORP_LLM_MOCK": "false",
    "CORP_CLOUD_ENABLED": "true",
    "CORP_CLAUDE_CODE": "true",
}

INSTALL_CMD = "npm install -g @anthropic-ai/claude-code"

INSTALL_EN = (
    "The `claude` CLI is not on this machine's PATH. Two steps, once:\n"
    f"  1. {INSTALL_CMD}\n"
    "  2. claude login   (pick your subscription)\n"
    "Then run `corparius claude` again. Or let corparius do step 1 for you: "
    "`corparius claude --install`."
)
INSTALL_FR = (
    "Le CLI `claude` n'est pas sur le PATH de cette machine. Deux étapes, "
    "une fois :\n"
    f"  1. {INSTALL_CMD}\n"
    "  2. claude login   (choisissez votre abonnement)\n"
    "Puis relancez `corparius claude`. Ou laissez corparius faire l'étape 1 : "
    "`corparius claude --install`."
)

# The trap this exists for: someone who has Claude Desktop reasonably reads
# "install Claude Code" as "you already did that". They are two products —
# Desktop is the chat window, and corparius drives the CLI headlessly
# (`claude -p ... --output-format json`), which a GUI cannot answer. Saying so
# costs three lines and saves an operator from concluding corparius is broken.
DESKTOP_EN = (
    "Claude Desktop is installed on this machine, but that is the chat app — "
    "corparius needs the Claude Code CLI, which is a separate install. Same "
    "subscription, no second one to buy.\n"
)
DESKTOP_FR = (
    "Claude Desktop est installé sur cette machine, mais c'est l'application "
    "de discussion — corparius a besoin du CLI Claude Code, qui s'installe à "
    "part. Même abonnement, rien de plus à souscrire.\n"
)


def desktop_installed() -> bool:
    """Is the Claude *desktop app* here? It is not the CLI and cannot stand in
    for it; knowing it is present only changes what we say, never what we do."""
    import glob
    import os
    import sys
    from pathlib import Path

    candidates: list[str] = []
    if sys.platform == "win32":
        local = os.environ.get("LOCALAPPDATA", "")
        candidates += [f"{local}\\AnthropicClaude", f"{local}\\Claude"]
        candidates += glob.glob("C:\\Program Files\\WindowsApps\\Claude_*")
    elif sys.platform == "darwin":
        candidates += ["/Applications/Claude.app", str(Path.home() / "Applications/Claude.app")]
    else:
        candidates += ["/opt/Claude", str(Path.home() / ".local/share/applications/claude.desktop")]
    return any(c and Path(c).exists() for c in candidates)


def install(timeout: int = 600) -> dict:
    """Run the npm install, on an explicit `--install`.

    Never implicit: this puts a global package on the operator's machine, which
    is not something a status check gets to decide.
    """
    npm = shutil.which("npm")
    if not npm:
        return {
            "ok": False,
            "detail": (
                "npm is not on this machine's PATH, and the CLI installs through "
                "it. Install Node.js (nodejs.org), then run this again — or "
                "follow claude.com/product/claude-code for the native installer."
            ),
        }
    try:
        out = proc.run([npm, "install", "-g", "@anthropic-ai/claude-code"], timeout=timeout)
    except proc.ProcError as exc:
        return {"ok": False, "detail": f"The install did not finish: {exc}"}
    if not out.ok:
        return {"ok": False, "detail": f"npm exited {out.returncode}:\n{out.tail()}"}
    if not resolve():
        return {
            "ok": False,
            "detail": (
                "npm reported success but `claude` is still not on the PATH. "
                "Open a new terminal — the npm global directory is added to the "
                "PATH at shell start — then run `corparius claude` again."
            ),
        }
    return {"ok": True, "detail": "The Claude Code CLI is installed."}


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
        desktop = desktop_installed()
        prefix = p(DESKTOP_EN, DESKTOP_FR) if desktop else ""
        return {
            "ok": False,
            "installed": False,
            "desktop": desktop,
            "detail": prefix + p(INSTALL_EN, INSTALL_FR),
        }
    try:
        out = proc.run(
            [exe, "-p", "Reply with the single word: ready", "--output-format", "json"],
            timeout=timeout,
        )
    except proc.ProcTimeout:
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
    except proc.ProcError as exc:
        return {
            "ok": False,
            "installed": True,
            "detail": p(f"Could not run the CLI: {exc}", f"Impossible de lancer le CLI : {exc}"),
        }
    if not out.ok:
        err = out.stderr.strip()
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
                f"The CLI exited {out.returncode}: {err[:200] or 'no output'}",
                f"Le CLI s'est arrêté ({out.returncode}) : {err[:200] or 'aucune sortie'}",
            ),
        }
    try:
        data = json.loads(out.stdout)
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


def plan(
    configured=None,
    local_trivial: str = "",
    all_tiers: bool = False,
    proven=None,
    catalogue=None,
    scores=None,
) -> dict:
    """What the one-press setup would write, for a preview and for the payload.

    A Claude subscription is metered in usage windows, not in tokens, so
    spending it on `draft_social_post` — TRIVIAL, every two hours — is the
    expensive mistake. Claude takes only HARD, which is strategy and the coder:
    the two roles where the difference is worth a window.

    `local_trivial` is the local model this machine was measured to be able to
    serve, or "" when it cannot serve one — in which case the trivial tier goes
    to a free provider like everything else. See corparius/hardware.py.

    Claude also closes the fallback chain, cheapest rung first, so a free
    provider going down escalates to Haiku and only then to Sonnet, instead of
    dropping straight to a local model that may not be installed.

    With nothing free connected there is nothing to prefer, so Claude serves
    every tier — the behaviour this had before. `all_tiers` asks for that
    deliberately.
    """
    from .routing import recommended_routing

    if all_tiers:
        return {**TOGGLES, **TIERS}
    routing = recommended_routing(
        list(configured or []),
        local_trivial,
        hard=HARD_TIER,
        fallback_tail=FALLBACK_LADDER,
        proven=proven or None,
        catalogue=catalogue or None,
        scores=scores or None,
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
