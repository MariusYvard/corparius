"""One exchange with the CEO. Rank 5.

The console had this and a terminal did not, and the barrier was one line:
`state.chats.setdefault(slug, deque(...))`. The history is now a parameter the caller owns —
the console passes its per-company deque, a terminal passes a list and gets a single turn.
That is honest rather than a limitation dressed up: chat history that survives a process is
schema 19's `chat_turns` table, not something this function can pretend to have.

The reply and the action are two halves of one answer. `directives.apply` is what makes the
sentence true, and if it changed something the change is appended — because the CEO answering
"I will pause the campaigns" and changing nothing is the failure this shape exists to end.
"""

from __future__ import annotations

from .. import structured
from ..kernel import i18n
from ..kernel.records import AgentRole
from ..providers.llm import HybridRouter
from ..roster import ROSTER
from . import directives


def once(store, settings, slug: str, message: str, history=None, lang: str = "en") -> dict:
    history = [] if history is None else history
    st = store.status(slug)
    tick = int(store.load_state(slug).get("tick", 0))
    open_tasks = store.list_tasks(slug, "approved")[:5]
    spec = ROSTER[AgentRole.CEO]
    snapshot = (
        f"Company snapshot: tick {tick}, {st['actions']} actions logged, "
        f"{st['tokens']} tokens spent, {st['pending_approvals']} approvals pending, "
        f"{st['open_tasks']} open tasks. Top open tasks: "
        + ("; ".join(t["title"] for t in open_tasks) or "none")
        + "."
    )
    system = (
        f"{spec.system_prompt} You are chatting with your human operator through "
        f"the corparius console. Be concise and concrete; reference the snapshot "
        # Not "Write 'reply' in French". A model reads that as an instruction to
        # translate the word, and answers "Réponse" — reproduced live against
        # llama-3.3-70b, three questions in a row, each answered with the label
        # instead of an answer. Name the field and the language separately.
        f"when relevant. The `reply` field holds your answer to the operator, "
        f"written in {'French' if lang == 'fr' else 'English'}; do not put a label "
        f"or a heading in it, only what you want to say. "
        f"Set 'intent' to one of {', '.join(directives.CEO_ACTIONS)} ONLY when the operator is "
        f"clearly asking to do that thing now; otherwise 'answer'. You never execute; "
        f"the operator confirms with a button. "
        # The part that makes the answer true rather than polite.
        f"You DO have real powers, and using them is how your answer becomes true "
        f"rather than polite. Roles: {', '.join(directives.PAUSABLE)}. "
        f"`pause` / `resume`: role names, when the operator does or does not want that "
        f"kind of work for now. A paused role stops on the next tick and the backlog "
        f"stops queueing for it. "
        f"`focus`: one short sentence when they say what the company should concentrate "
        f"on; it replaces the routine backlog until they change it. Empty string clears it. "
        f'`cadence`: {{"social": 24}} to change how many hours between a role\'s turns. '
        # Added to the schema and to _apply_directives without ever being named
        # here, so the CEO could not know the power existed. Asked to put design
        # on claudecode:opus it answered "J'approuve l'utilisation de Claudecode
        # Opus pour le design" and wrote nothing — the empty promise, arriving
        # through the field meant to end it. A power the model is not told about
        # is a power nothing can reach.
        f'`model`: {{"design": "claudecode:opus"}} to put one role on one model, '
        f"without moving a whole tier. The value must carry the provider prefix "
        f"(`local:`, `cloud:`, `claudecode:` or a provider name), or it is refused. "
        f"`approve`: tool names whose pending request they are approving in words. "
        f"Never claim to have done any of these unless you put it in the field, and never "
        f"name a role that is not in the list above. Leave them empty for an ordinary "
        f"answer. {snapshot}"
    )
    messages = (
        [{"role": "system", "content": system}]
        + [{"role": m["role"], "content": m["text"]} for m in history]
        + [{"role": "user", "content": message}]
    )
    # One structured call classifies intent and writes the reply. The harness
    # returns the same shape whatever model answered; in mock or on a weak model
    # it falls back to intent=answer, so the chat degrades to plain conversation.
    router = HybridRouter(settings)
    result = structured.ask(router, messages, directives.CEO_SCHEMA, difficulty=spec.difficulty)
    for u in result.usages:
        store.record_usage(slug, "ceo", u.input_tokens, u.output_tokens)
    # `or message` echoed the operator's own question back at them, which reads
    # like an answer and is not one. When the model said nothing usable, say so.
    reply = (result.data.get("reply") or "").strip()
    unanswered = not reply
    if unanswered:
        reply = i18n.pick(
            lang,
            "The model did not answer. It may be rate-limited or the tier may be "
            "misconfigured — the Providers tab shows which one replied.",
            "Le modèle n'a pas répondu. Il est peut-être limité en débit, ou le palier "
            "est mal configuré — l'onglet Providers montre lequel a répondu.",
        )
    # Act on it, then report what actually happened. The CEO used to answer
    # "I will pause the campaigns" and change nothing; now the sentence and the
    # state agree, or the sentence is corrected.
    changed = directives.apply(store, slug, result.data, lang)
    if changed:
        reply = "\n\n".join(part for part in (reply, changed) if part)
        unanswered = False
    intent = result.data.get("intent", "answer")
    proposal = None
    if intent in directives.CEO_ACTIONS and not result.fell_back:
        spec_a = dict(directives.CEO_ACTIONS[intent])
        body = dict(spec_a["body"])
        if intent == "run_day":
            body["ticks"] = max(1, min(int(result.data.get("ticks", 24)), 48))
        proposal = {
            "intent": intent,
            "endpoint": spec_a["endpoint"],
            "body": body,
            "needs_company": not spec_a.get("no_company"),
            "label": i18n.pick(lang, spec_a["label_en"], spec_a["label_fr"]),
        }
    provider, _, model = result.source.partition(":")  # "mock:haiku" -> mock, haiku
    history.append({"role": "user", "text": message})
    history.append(
        {
            "role": "assistant",
            "text": reply,
            "model": model,
            "provider": provider,
            "unanswered": unanswered,
        }
    )
    return {
        "ok": True,
        "reply": reply,
        # So the page can render a failure as a failure rather than as the CEO
        # having said something odd.
        "unanswered": unanswered,
        "model": model,
        "provider": provider,
        "proposal": proposal,
        "history": list(history),
    }
