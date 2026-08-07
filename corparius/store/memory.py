"""Durable facts, and the ranking that decides which reach a prompt."""

from __future__ import annotations

import time

from ..kernel.vectors import cosine, hash_embed
from .base import Connected, _locked, _words


class MemoryMixin(Connected):
    @_locked
    def remember(self, company, agent, fact, why="", pinned=False, max_rows=200) -> int:
        """Write down something the company learned. Returns the row id, or 0
        when the same fact is already held.

        Deduplicated on the words, not on the string: the same observation
        restated with different word order, casing or punctuation is recognised
        and dropped, which is what an agent asked the same question every day
        actually produces. It is *not* paraphrase detection — the comparison is
        cosine over kernel.vectors.hash_embed, a bag-of-tokens embedding, so "coaches
        renew" and "our coaching customers stay" are two facts as far as this is
        concerned. Catching those would need a real embedding model, and would
        risk merging two facts that only sound alike, which is worse than
        keeping one line twice.

        Reusing hash_embed is what keeps this dependency-free and offline, like
        the loop guard it was written for.
        """
        fact = str(fact).strip()
        if not fact:
            return 0
        target = hash_embed(_words(fact))
        for row in self.db.execute(
            "SELECT fact FROM memory WHERE company=?", (company,)
        ).fetchall():
            if cosine(target, hash_embed(_words(row["fact"]))) >= 0.95:
                return 0
        cur = self.db.execute(
            "INSERT INTO memory (company, agent, fact, why, pinned, ts) VALUES (?,?,?,?,?,?)",
            (company, agent, fact, str(why).strip(), 1 if pinned else 0, time.time()),
        )
        # max_rows caps the *unpinned* facts, oldest dropped first. A pinned
        # fact is the operator saying "this one stays", so it is neither counted
        # against the cap nor discarded by it — otherwise pinning enough facts
        # would silently stop the company from learning anything new.
        self.db.execute(
            "DELETE FROM memory WHERE id IN ("
            " SELECT id FROM memory WHERE company=? AND pinned=0"
            " ORDER BY ts DESC LIMIT -1 OFFSET ?)",
            (company, max(0, int(max_rows))),
        )
        self.db.commit()
        assert cur.lastrowid is not None
        return cur.lastrowid

    @_locked
    def recall(self, company, query="", limit=5) -> list[dict]:
        """The facts most worth putting in front of this particular prompt.

        Pinned first, then by similarity to the query, then by recency. Ranked in Python
        rather than in SQL, and the reason given here used to be wrong: it said the
        alternative was "either a vector extension or a LIKE that matches words instead of
        meaning". **FTS5 is compiled into the standard library's sqlite3** — measured, SQLite
        3.50.4 — and it is neither of those; it is real BM25 ranking with no third dependency.
        A docstring that rules out the option it is actually choosing against is worse than
        one that says nothing.

        Measured against the real corpus before deciding (55 facts, 13 933 characters, mean
        fact 137 chars). FTS5 is not the right answer here, for a reason that has nothing to
        do with quality:

          * **The query is a whole prompt**, not keywords. `agents._recall` passes
            `tool.draft_prompt(ctx)` — 40 to 613 characters, mean 258. `MATCH` takes a query
            expression, so using it means inventing a keyword extractor, and the one written
            for the measurement needed a hand-kept stop list, half of it stop-words from the
            language line every prompt carries. That is a new heuristic, not a removed one.
          * **It under-fills the top k.** On four real prompts FTS5 returned 5, 5, 2 and 1
            candidates; an OR of a few keywords simply misses. This feature exists to put
            `limit` facts in front of a prompt.
          * The two rankings overlap on 0 to 2 of 5, and there is **no labelled data** here to
            say which is right. Swapping on the strength of that would be replacing one
            intuition with another.

        What the same measurement did confirm is that this ranking discriminates: over the
        real corpus the spread between best and worst is 0.32 to 0.41 with the median well
        below the best, so it is selecting rather than shuffling. `tests/test_memory_store.py`
        pins that.

        `hash_embed` compares bags of words, and a prompt is a bag of words. FTS5 stays the
        right tool for a search box, which this is not."""
        rows = [
            dict(r)
            for r in self.db.execute(
                "SELECT * FROM memory WHERE company=? ORDER BY ts DESC", (company,)
            ).fetchall()
        ]
        if not rows:
            return []
        if query.strip():
            target = hash_embed(query)
            for row in rows:
                row["score"] = cosine(target, hash_embed(f"{row['fact']} {row['why']}"))
        else:
            for row in rows:
                row["score"] = 0.0
        rows.sort(key=lambda r: (r["pinned"], r["score"], r["ts"]), reverse=True)
        return rows[: max(0, int(limit))]

    @_locked
    def list_memory(self, company) -> list[dict]:
        rows = self.db.execute(
            "SELECT * FROM memory WHERE company=? ORDER BY pinned DESC, ts DESC", (company,)
        ).fetchall()
        return [dict(r) for r in rows]

    @_locked
    def pin_memory(self, memory_id, pinned=True) -> bool:
        cur = self.db.execute(
            "UPDATE memory SET pinned=? WHERE id=?", (1 if pinned else 0, memory_id)
        )
        self.db.commit()
        return cur.rowcount > 0

    @_locked
    def forget(self, memory_id) -> bool:
        cur = self.db.execute("DELETE FROM memory WHERE id=?", (memory_id,))
        self.db.commit()
        return cur.rowcount > 0
