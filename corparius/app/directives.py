"""What the CEO may be told to do, and applying an operator's decision. Rank 5.

The half of the CEO conversation that *acts*. `chat` writes a sentence; this makes it true — the
CEO used to answer "I will pause the campaigns" and change nothing, and the whole point of these
fields is that the sentence and the state agree or the sentence is corrected.

Three of the things in here were paid for the hard way, and the comments say which:

  * `model` was added to the schema and to this function without ever being named in the
    prompt, so the CEO could not know the power existed. Asked to put design on
    `claudecode:opus` it answered "J'approuve l'utilisation de Claudecode Opus pour le design"
    and wrote nothing — the empty promise, arriving through the field meant to end it.
  * a pin without a provider prefix is refused rather than stored, because every prefix-less
    value resolves to `local:` and a role would silently run on a model nobody chose.
  * the reply is never the operator's own question echoed back; `or message` reads like an
    answer and is not one.

`PAUSABLE` and `_CEO_SCHEMA` live here rather than in the chat module because this is what reads
them. The prompt that *describes* them is next door, and `tests/test_ceo_powers.py` is what
holds the two together — a power in the schema and not in the prompt is unreachable, and it
happened.
"""

from __future__ import annotations

import logging

from ..kernel import i18n
from ..orchestrator import _known_target

log = logging.getLogger("corparius.app.directives")

# What the CEO chat can propose. Each maps to an existing, audited endpoint the
# operator confirms with a click, so the chat never mutates on its own and money
# or production still passes the HITL gate on the resulting run. The LLM only
# routes intent; it opens no new path.
CEO_ACTIONS: dict[str, dict] = {
    "run_day": {
        "endpoint": "/api/run",
        "body": {"ticks": 24},
        "label_en": "Run a day",
        "label_fr": "Lancer une journée",
    },
    "run_loop": {
        "endpoint": "/api/run",
        "body": {"ticks": 24, "loop": True},
        "label_en": "Run continuously",
        "label_fr": "Lancer en continu",
    },
    "deploy": {
        "endpoint": "/api/deploy",
        "body": {},
        "label_en": "Publish the site",
        "label_fr": "Publier le site",
    },
    "build_site": {
        "endpoint": "/api/site",
        "body": {},
        "label_en": "Build the site",
        "label_fr": "Générer le site",
    },
    "backup": {
        "endpoint": "/api/backup",
        "body": {},
        "label_en": "Back up now",
        "label_fr": "Sauvegarder",
    },
    "use_claude": {
        "endpoint": "/api/claude/setup",
        "body": {},
        "no_company": True,
        "label_en": "Use my Claude subscription",
        "label_fr": "Utiliser mon abonnement Claude",
    },
}

# Roles the operator can stand down or bring back. Closed on purpose: a
# directive naming a role that does not exist would be a promise nothing keeps,
# which is the failure this whole mechanism exists to end.
PAUSABLE = ("social", "outreach", "support", "ads", "finance", "strategy", "competitor", "design")

CEO_SCHEMA = {
    "reply": {"type": "str", "required": True, "max_len": 800},
    "intent": {"type": "str", "default": "answer", "choices": ["answer"] + list(CEO_ACTIONS)},
    "ticks": {"type": "int", "default": 24},
    # What the CEO is committing the company to, in a form the runtime obeys.
    # Without these the chat was a conversation held over a machine that could
    # not hear it: an operator said "too early for cold emailing", the CEO
    # answered "I will pause the campaigns", and the next tick drafted another.
    "pause": {"type": "list", "default": []},
    "resume": {"type": "list", "default": []},
    # What the company should be working on. Read by `create_tasks`, which
    # otherwise queues its housekeeping baseline on top of whatever the operator
    # just asked for — and re-arms a role they had just stood down.
    "focus": {"type": "str", "default": "", "max_len": 200},
    # {"social": 24} — hours between turns, per role. The alternative was editing
    # company.yaml, which is not a thing anyone does mid-conversation.
    "cadence": {"type": "dict", "default": {}, "shape": '{"social": 24}'},
    # {"design": "openrouter:nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free"} —
    # one role's model, without moving a whole tier. Only three tiers are
    # configurable and nine roles take theirs from one of them, so giving the
    # design agent a model that can read a picture used to mean moving the normal
    # tier: measured on a real configuration, 535 tok/s down to 49 across four
    # roles to gain vision on one.
    "model": {"type": "dict", "default": {}, "shape": '{"design": "claudecode:opus"}'},
    # Bonus, and deliberately narrow: name a tool whose pending request the
    # operator is approving in words. The console button stays exactly as it is;
    # this is a second door, not a replacement.
    "approve": {"type": "list", "default": []},
}


def apply(store, slug: str, data: dict, lang: str) -> str:
    """Turn the CEO's `pause` / `resume` lists into standing directives.

    Returns a line naming what changed, appended to the reply so the operator
    reads the effect rather than the intention. A role the model invented is
    dropped and not mentioned: promising to pause `marketing` — which is not a
    role — would be exactly the empty promise this replaces.
    """

    def names(key):
        raw = data.get(key) or []
        if isinstance(raw, str):
            raw = [raw]
        return [n for n in (str(x).strip().lower() for x in raw) if n in PAUSABLE]

    paused, resumed = names("pause"), names("resume")
    for role in paused:
        store.add_directive(slug, "pause", role, "asked in the CEO chat")
    for role in resumed:
        for d in store.directives(slug, "pause"):
            if d["target"] == role:
                store.clear_directive(d["id"])
    # A stated priority, which `create_tasks` reads instead of its baseline.
    focus = str(data.get("focus") or "").strip()
    if focus:
        store.add_directive(slug, "focus", "", focus)
    elif isinstance(data.get("focus"), str) and "focus" in data:
        for d in store.directives(slug, "focus"):
            store.clear_directive(d["id"])

    # Cadence, in hours, per role. Bounded: zero would busy-loop a role and a
    # year would be indistinguishable from off, and neither is what anybody
    # means. Out of range is dropped rather than clamped silently.
    cadence = {}
    raw_cadence = data.get("cadence")
    if isinstance(raw_cadence, dict):
        for role, hours in raw_cadence.items():
            role = str(role).strip().lower()
            try:
                hours = int(hours)
            except (TypeError, ValueError):
                continue
            if role in PAUSABLE and 1 <= hours <= 168:
                store.add_directive(slug, "cadence", role, str(hours))
                cadence[role] = hours

    # One role's model. Refused rather than stored when the prefix is not a
    # provider this build routes to: an unknown target makes every turn of that
    # role fall through the chain to local, which reads as a slow day and not as a
    # typo. The refusal is named in the reply below, because a pin the operator
    # believes they set is worse than one they know was rejected.
    pins, refused_pins = {}, []
    raw_models = data.get("model")
    if isinstance(raw_models, dict):
        for role, model in raw_models.items():
            role, model = str(role).strip().lower(), str(model).strip()
            if role not in PAUSABLE or not model:
                continue
            if _known_target(model):
                store.add_directive(slug, "model", role, model)
                pins[role] = model
            else:
                refused_pins.append(f"{role} → {model}")

    # Bonus: approving in words. Narrow on purpose — it approves a request that
    # already exists and was already shown, and the console button is untouched.
    approved = []
    for name in {str(x).strip() for x in (data.get("approve") or [])}:
        waiting = store.pending_approval_for(slug, name)
        if waiting:
            store.set_approval_status(waiting["id"], "approved", "approved in the CEO chat")
            approved.append(name)

    parts = []
    if paused:
        parts.append(
            i18n.pick(
                lang,
                f"Stood down from the next tick: {', '.join(paused)}.",
                f"Mis en veille dès le prochain tour : {', '.join(paused)}.",
            )
        )
    if resumed:
        parts.append(
            i18n.pick(
                lang, f"Started again: {', '.join(resumed)}.", f"Redémarré : {', '.join(resumed)}."
            )
        )
    if focus:
        parts.append(i18n.pick(lang, f"Priority set: {focus}", f"Priorité fixée : {focus}"))
    if cadence:
        spelled = ", ".join(f"{r} every {h}h" for r, h in cadence.items())
        spelled_fr = ", ".join(f"{r} toutes les {h} h" for r, h in cadence.items())
        parts.append(i18n.pick(lang, f"Cadence: {spelled}.", f"Cadence : {spelled_fr}."))
    if pins:
        spelled = ", ".join(f"{r} on {m}" for r, m in pins.items())
        spelled_fr = ", ".join(f"{r} sur {m}" for r, m in pins.items())
        parts.append(i18n.pick(lang, f"Model: {spelled}.", f"Modèle : {spelled_fr}."))
    if refused_pins:
        # Named, not swallowed. A pin the operator believes they set is worse than
        # one they know was refused.
        joined = ", ".join(refused_pins)
        parts.append(
            i18n.pick(
                lang,
                f"Refused, no provider by that name: {joined}.",
                f"Refusé, aucun fournisseur de ce nom : {joined}.",
            )
        )
    if approved:
        parts.append(
            i18n.pick(
                lang, f"Approved: {', '.join(approved)}.", f"Approuvé : {', '.join(approved)}."
            )
        )
    if any((paused, resumed, focus, cadence, pins, refused_pins, approved)):
        log.info(
            "%s: CEO paused=%s resumed=%s focus=%r cadence=%s approved=%s",
            slug,
            paused or "-",
            resumed or "-",
            focus,
            cadence or "-",
            approved or "-",
        )
    return " ".join(parts)
