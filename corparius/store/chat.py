"""What the operator and the CEO said to each other. Schema 21.

Two docstrings promised this table before it existed. `app/chat.py`: *"chat history that survives a
process is schema 19's `chat_turns` table, not something this function can pretend to have."*
`cli/operate.cmd_ceo`: *"conversation that survives a process is a store table, not something a
one-shot command can pretend to have."* Both were honest about the limit and both named the fix; the
table was simply never built, and the plan named it in the same breath as `jobs`.

Three things change, and they are the same three that changed for runs and for the sweep:

  * **A restart keeps the conversation.** It lived in `UiState.chats`, a deque per company in the
    console's process, so closing the console lost every exchange — including the ones where the CEO
    paused a role or set a focus, which are the turns an operator most needs to look back at.
  * **A terminal is in the same conversation.** `corparius ceo` passed a fresh list and got a single
    turn with no memory of anything. Now it reads what the console said and the console reads back:
    one conversation per company, whoever is typing. That is exactly the argument `cmd_run` makes for
    recording a foreground run in `jobs`.
  * **A second client can read it.** The premise of the whole v1 contract is a phone consulting a core
    it did not start, and an in-process deque is not consultable.

**Bounded by rows, not by tokens.** `HISTORY_KEPT` caps what a prompt is built from, and the table
keeps everything: an operator scrolling back is a different question from what a model is given, and
the console already learned that distinction with documents (`MAX_CHARS` for a prompt, no cap for a
person reading their own file).
"""

from __future__ import annotations

import time

from .base import Connected, _locked

# Turns handed to the model as context. Twelve, not the deque's thirty: a turn is a paragraph and the
# CEO prompt already carries a company snapshot and its whole powers list. Thirty exchanges of that
# was a prompt whose oldest half never changed the answer and always cost tokens.
HISTORY_KEPT = 12


class ChatMixin(Connected):
    @_locked
    def add_chat_turn(
        self,
        company: str,
        role: str,
        text: str,
        model: str = "",
        provider: str = "",
        unanswered: bool = False,
    ) -> int:
        """Append one turn. Returns its row id.

        `unanswered` is stored rather than derived, because it is a fact about what happened: the model
        was called and said nothing usable. Recomputing it later from an empty `text` would be wrong —
        the reply the operator saw is the sentence explaining the silence, so the text is not empty.
        """
        cur = self.db.execute(
            "INSERT INTO chat_turns (company, role, text, model, provider, unanswered, ts)"
            " VALUES (?,?,?,?,?,?,?)",
            (
                company,
                str(role),
                str(text),
                str(model),
                str(provider),
                1 if unanswered else 0,
                time.time(),
            ),
        )
        self.db.commit()
        assert cur.lastrowid is not None
        return cur.lastrowid

    @_locked
    def chat_history(self, company: str, limit: int = HISTORY_KEPT) -> list[dict]:
        """The last `limit` turns, **oldest first**.

        Selected newest-first and reversed, which is the only way to take the *last* N from a growing
        table — and returned oldest-first because that is the order a conversation is read in and the
        order a prompt needs. Getting that backwards would hand the model the exchange in reverse,
        which reads as coherent and answers the wrong question.
        """
        rows = self.db.execute(
            "SELECT * FROM chat_turns WHERE company=? ORDER BY id DESC LIMIT ?",
            (company, max(0, int(limit))),
        ).fetchall()
        return [
            {
                "role": r["role"],
                "text": r["text"],
                "model": r["model"],
                "provider": r["provider"],
                "unanswered": bool(r["unanswered"]),
                "ts": r["ts"],
            }
            for r in reversed(rows)
        ]

    @_locked
    def forget_chat(self, company: str) -> int:
        """Drop the conversation. Returns how many turns went.

        The operator's own history is theirs to clear, the same argument as `forget` for a memory: a
        transcript that can only be removed by opening the database is a transcript they do not own.
        Not archived, unlike a skill — a skill is knowledge the curator may want back, and a chat is a
        conversation they have decided to end.
        """
        cur = self.db.execute("DELETE FROM chat_turns WHERE company=?", (company,))
        self.db.commit()
        return cur.rowcount
