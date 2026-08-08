"""Proving the mail account works, and what is left to set up. Rank 5.

`check` sends a real message and then reads the box. That is deliberate and it is the same
bargain `integrations.smtp_check` documents: a subscription message is spent to prove the setup,
because nothing cheaper actually proves it. "Configured" and "works" are different facts, and
this project's discipline is the second one.

**The console could do it and a terminal could not**, which is backwards for exactly the machine
where it matters. `doctor` reports whether the settings are present; on a headless box that is
the difference between believing the mail is wired and knowing it. Nothing in the CLI sent a
test message at all.

The two halves are reported separately because they fail for different reasons — SMTP is
outbound and a wrong port, IMAP is inbound and a wrong folder — and an operator needs to know
which one is broken, not that "mail" is.
"""

from __future__ import annotations

from ..config import cfg, settings_spec
from ..kernel import i18n
from ..providers import mailbox
from ..providers.integrations import smtp_check


def check(to: str = "", lang: str = "en") -> dict:
    """Prove the mail account in one press: send, then read. Reported as two
    lines because they fail for different reasons and an operator needs to know
    which half is broken."""
    send = smtp_check(to, lang=lang)
    read = mailbox.check(lang=lang)
    sending = i18n.pick(lang, "Sending", "Envoi")
    reading = i18n.pick(lang, "Reading", "Lecture")
    lines = [f"{sending}: {send['detail']}", f"{reading}: {read['detail']}"]
    if not send["configured"] and not read["configured"]:
        return {
            "ok": False,
            "detail": i18n.pick(
                lang,
                "No mail account set yet. Pick a provider above, give the address "
                "and an app password.",
                "Aucun compte mail réglé. Choisissez un fournisseur ci-dessus, donnez "
                "l'adresse et un mot de passe d'application.",
            ),
        }
    return {
        "ok": bool(send["ok"] and read["ok"]),
        "send_ok": send["ok"],
        "read_ok": read["ok"],
        "detail": "\n".join(lines),
    }


def steps() -> dict:
    """The per-provider steps, each carrying whether it is actually done.

    Resolved here rather than in the page because "done" is a fact about this
    installation's settings, not about the browser — the same reason the
    approval panel resolves what a tool does server-side.

    A step with no `needs` is one corparius cannot check: installing Proton
    Bridge, reading a password off somebody else's dashboard. Those report
    `checkable: false` and the console shows them as something to do rather
    than as something outstanding, because a step that can never turn green is
    worse than no state at all.
    """
    out: dict[str, list[dict]] = {}
    for provider, steps in settings_spec.MAIL_STEPS.items():
        resolved = []
        for step in steps:
            needs = step.get("needs") or []
            resolved.append(
                {
                    "en": step["en"],
                    "fr": step["fr"],
                    "url": step.get("url", ""),
                    "checkable": bool(needs),
                    "done": bool(needs) and all(cfg.get(key, "").strip() for key in needs),
                }
            )
        out[provider] = resolved
    return out
