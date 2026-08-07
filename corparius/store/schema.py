"""The tables, the version, and one migration per version.

Separated from the queries for the reason the plan gives: a 1 672-line file held the schema,
sixteen migrations and eighty-three accessors, and only the first two are about the *shape* of
the database. Nothing here is touched by the split — not `PRAGMA user_version`, not the
numbering, not a single migration body. `tests/test_registries.py` asserts there is exactly one
migration per version up to the current one, because a gap means a store stamped forward and
never actually migrated, and the failure surfaces much later as a query.
"""

from __future__ import annotations

import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS actions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company TEXT, agent TEXT, tool TEXT, parameters TEXT,
    output TEXT, ok INTEGER, ts REAL,
    source TEXT, attempts INTEGER, fell_back INTEGER, errors TEXT
);
CREATE TABLE IF NOT EXISTS token_usage (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company TEXT, agent TEXT, input_tokens INTEGER, output_tokens INTEGER, ts REAL,
    cost REAL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS approvals (
    id TEXT PRIMARY KEY,
    company TEXT, agent TEXT, tool TEXT, parameters TEXT,
    status TEXT, note TEXT, ts REAL, detail TEXT
);
CREATE TABLE IF NOT EXISTS state (
    company TEXT PRIMARY KEY, data TEXT
);
CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company TEXT, title TEXT, target TEXT, priority INTEGER,
    status TEXT, created_by TEXT, note TEXT, ts REAL, tool TEXT, why TEXT
);
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY, value TEXT NOT NULL,
    secret INTEGER NOT NULL DEFAULT 0, updated_at REAL
);
CREATE TABLE IF NOT EXISTS outreach (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company TEXT, email TEXT, message_id TEXT, subject TEXT, ts REAL,
    replied_at REAL, reply_snippet TEXT
);
CREATE INDEX IF NOT EXISTS outreach_by_email ON outreach (company, email);
CREATE TABLE IF NOT EXISTS rules (
    company TEXT, tool TEXT, scope TEXT, note TEXT, ts REAL,
    PRIMARY KEY (company, tool)
);
CREATE TABLE IF NOT EXISTS memory (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company TEXT, agent TEXT, fact TEXT, why TEXT, pinned INTEGER DEFAULT 0, ts REAL
);
CREATE INDEX IF NOT EXISTS memory_by_company ON memory (company, pinned, ts);
CREATE TABLE IF NOT EXISTS skill_usage (
    company TEXT, skill TEXT, uses INTEGER DEFAULT 0, last_used REAL,
    PRIMARY KEY (company, skill)
);
CREATE TABLE IF NOT EXISTS inbox (
    id TEXT PRIMARY KEY,
    company TEXT, agent TEXT, kind TEXT, title TEXT, body TEXT, options TEXT,
    state TEXT, resolution TEXT, resolved_at REAL, ts REAL, fix TEXT
);
CREATE INDEX IF NOT EXISTS inbox_by_company ON inbox (company, state, ts);
CREATE TABLE IF NOT EXISTS machine (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    cores INTEGER, ram_total INTEGER, ram_available INTEGER,
    tokens_per_second REAL, load_seconds REAL, placement TEXT, model TEXT, ts REAL
);
CREATE TABLE IF NOT EXISTS drafts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company TEXT, kind TEXT, channel TEXT, body TEXT,
    state TEXT, note TEXT, ts REAL, published_at REAL
);
CREATE INDEX IF NOT EXISTS drafts_by_company ON drafts (company, state, ts);
CREATE TABLE IF NOT EXISTS model_catalogue (
    id INTEGER PRIMARY KEY CHECK (id = 1), models TEXT, ts REAL
);
CREATE TABLE IF NOT EXISTS directives (
    id INTEGER PRIMARY KEY AUTOINCREMENT, company TEXT, kind TEXT, target TEXT,
    note TEXT, active INTEGER DEFAULT 1, ts REAL
);
CREATE INDEX IF NOT EXISTS directives_by_company ON directives (company, active);
CREATE TABLE IF NOT EXISTS decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT, company TEXT, text TEXT, why TEXT, ts REAL
);
CREATE INDEX IF NOT EXISTS decisions_by_company ON decisions (company, ts);
CREATE TABLE IF NOT EXISTS model_probes (
    provider TEXT, model TEXT, state TEXT, detail TEXT, status INTEGER, ms INTEGER, ts REAL,
    tok_s REAL, json_ok INTEGER, samples INTEGER, failures INTEGER, measured_at REAL,
    vision_ok INTEGER,
    PRIMARY KEY (provider, model)
);
"""


# Bump this and add a migration below whenever the schema changes in a way that
# an existing store must be brought forward through. The version is tracked in
# the database itself via `PRAGMA user_version`, so an upgrade migrates in place
# instead of relying on the operator to back up and recreate.
SCHEMA_VERSION = 18


def _migration_1(db: sqlite3.Connection) -> None:
    """Stores created before the CEO wired tasks to executable tools lack the
    tasks.tool column. Guarded so it is a no-op on fresh DBs (the column is in
    SCHEMA) and on re-runs."""
    try:
        db.execute("ALTER TABLE tasks ADD COLUMN tool TEXT")
    except sqlite3.OperationalError:
        pass


def _migration_2(db: sqlite3.Connection) -> None:
    """Standing permission rules ("approve, and stop asking"), added with the
    risk-classed permission engine. CREATE TABLE IF NOT EXISTS in SCHEMA already
    covers fresh stores; this exists so an upgrade in place reaches the same
    shape without the operator recreating the database."""
    db.execute(
        "CREATE TABLE IF NOT EXISTS rules ("
        " company TEXT, tool TEXT, scope TEXT, note TEXT, ts REAL,"
        " PRIMARY KEY (company, tool))"
    )


def _migration_3(db: sqlite3.Connection) -> None:
    """Durable memory, added when three days of EOD summaries stopped being
    enough. Same guarded shape as _migration_2."""
    db.execute(
        "CREATE TABLE IF NOT EXISTS memory ("
        " id INTEGER PRIMARY KEY AUTOINCREMENT,"
        " company TEXT, agent TEXT, fact TEXT, why TEXT, pinned INTEGER DEFAULT 0, ts REAL)"
    )
    db.execute("CREATE INDEX IF NOT EXISTS memory_by_company ON memory (company, pinned, ts)")


def _migration_4(db: sqlite3.Connection) -> None:
    """The typed inbox: questions an agent could not ask before, and notices a
    frozen session could not send. Same guarded shape as the two above."""
    db.execute(
        "CREATE TABLE IF NOT EXISTS inbox ("
        " id TEXT PRIMARY KEY,"
        " company TEXT, agent TEXT, kind TEXT, title TEXT, body TEXT, options TEXT,"
        " state TEXT, resolution TEXT, resolved_at REAL, ts REAL)"
    )
    db.execute("CREATE INDEX IF NOT EXISTS inbox_by_company ON inbox (company, state, ts)")


def _migration_5(db: sqlite3.Connection) -> None:
    """Cost per call, added when OpenRouter turned out to report it in the usage
    block corparius was already parsing for tokens. Existing rows keep 0, which
    reads as "not reported" rather than "free"."""
    try:
        db.execute("ALTER TABLE token_usage ADD COLUMN cost REAL DEFAULT 0")
    except sqlite3.OperationalError:
        pass


def _migration_6(db: sqlite3.Connection) -> None:
    """The measured machine profile, added when the routing turned out to decide
    the trivial tier on nothing but "Ollama's port answered". One row, pinned by
    a CHECK: there is exactly one machine."""
    db.execute(
        "CREATE TABLE IF NOT EXISTS machine ("
        " id INTEGER PRIMARY KEY CHECK (id = 1),"
        " cores INTEGER, ram_total INTEGER, ram_available INTEGER,"
        " tokens_per_second REAL, load_seconds REAL, placement TEXT, model TEXT, ts REAL)"
    )


def _migration_7(db: sqlite3.Connection) -> None:
    """Somewhere for a draft to land.

    The social agent was the biggest line in one operator's spend — 29 065
    tokens — and `schedule_post` returned a sentence. Nothing was stored, so
    every post it wrote was gone before the next tick wrote another. A draft
    nobody can read is a draft nobody asked for.
    """
    db.execute(
        "CREATE TABLE IF NOT EXISTS drafts ("
        " id INTEGER PRIMARY KEY AUTOINCREMENT,"
        " company TEXT, kind TEXT, channel TEXT, body TEXT,"
        " state TEXT, note TEXT, ts REAL, published_at REAL)"
    )
    db.execute("CREATE INDEX IF NOT EXISTS drafts_by_company ON drafts (company, state, ts)")


def _migration_8(db: sqlite3.Connection) -> None:
    """What the operator is actually being asked to approve.

    An approval carried `parameters`, and `parameters` carried the draft cut to
    80 characters — because the id is a hash of them, and a longer draft would
    have made the same request look like a new one every time. So approving
    `send_outreach` meant approving an email nobody could read. The full text
    goes here instead, where nothing hashes it.
    """
    try:
        db.execute("ALTER TABLE approvals ADD COLUMN detail TEXT")
    except sqlite3.OperationalError:
        pass


def _migration_9(db: sqlite3.Connection) -> None:
    """Where to go to make the notice stop.

    `scan_replies` and `triage_inbox` said "no mailbox connected" on every tick
    of every run, as a log line — true, repeated forever, and pointing at
    nothing an operator could click. A notice that names its own remedy can be
    filed once and answered once.
    """
    try:
        db.execute("ALTER TABLE inbox ADD COLUMN fix TEXT")
    except sqlite3.OperationalError:
        pass


def _migration_10(db: sqlite3.Connection) -> None:
    """What each provider's models actually did when called.

    A catalogue lists models that exist. On NVIDIA, 8 of 14 sampled catalogue
    entries answered 404 for the owner's own key. Knowing that is worth keeping:
    the previous preflight overwrote one report per run and remembered nothing
    per provider, so the same 404s were rediscovered every time.

    Keyed on (provider, model) so a later run updates a verdict instead of
    appending a second one, and so knowledge accumulates across runs.
    """
    db.execute(
        "CREATE TABLE IF NOT EXISTS model_probes ("
        " provider TEXT, model TEXT, state TEXT, detail TEXT, status INTEGER, ms INTEGER,"
        " ts REAL, PRIMARY KEY (provider, model))"
    )


def _migration_11(db: sqlite3.Connection) -> None:
    """How a model performs, not just whether it answers.

    "It answered" is a poor basis for a routing decision. Measured on real
    providers: 547 tok/s on one, 10 on another, and one model in the owner's own
    fallback chain that cannot produce a JSON object at all — which an
    availability probe cannot see, and which breaks every tool that goes through
    corparius/structured.py.
    """
    for column, kind in (
        ("tok_s", "REAL"),
        ("json_ok", "INTEGER"),
        ("samples", "INTEGER"),
        ("failures", "INTEGER"),
        ("measured_at", "REAL"),
    ):
        try:
            db.execute(f"ALTER TABLE model_probes ADD COLUMN {column} {kind}")
        except sqlite3.OperationalError:
            pass


def _migration_12(db: sqlite3.Connection) -> None:
    """The provider catalogue, in its own table rather than in `settings`.

    It went in `settings` first and that was wrong twice over: 400 KB of JSON
    appeared as a row among the operator's own configuration, and it travelled
    into backups as if somebody had set it.
    """
    db.execute(
        "CREATE TABLE IF NOT EXISTS model_catalogue ("
        " id INTEGER PRIMARY KEY CHECK (id = 1), models TEXT, ts REAL)"
    )
    db.execute("DELETE FROM settings WHERE key='CORP_MODEL_CATALOGUE'")


def _migration_13(db: sqlite3.Connection) -> None:
    """What the operator told the CEO, in a form the runtime can obey.

    The CEO chat read the store and wrote nothing. So an operator could say
    "too early for cold emailing, focus on the prototype", watch the CEO answer
    "I will pause the campaigns", and then watch the next tick draft another
    cold email. The chat was a conversation held over a machine that could not
    hear it, which is worse than no chat: it promised.
    """
    db.execute(
        "CREATE TABLE IF NOT EXISTS directives ("
        " id INTEGER PRIMARY KEY AUTOINCREMENT, company TEXT, kind TEXT, target TEXT,"
        " note TEXT, active INTEGER DEFAULT 1, ts REAL)"
    )
    db.execute("CREATE INDEX IF NOT EXISTS directives_by_company ON directives (company, active)")


def _migration_14(db: sqlite3.Connection) -> None:
    """Decisions, kept apart from facts.

    `memory` holds what the company observed. A decision is a different animal:
    it binds the future, and it should be reread before the next one is taken.
    Mixing them is why one run produced three contradicting priorities in three
    hours.
    """
    db.execute(
        "CREATE TABLE IF NOT EXISTS decisions ("
        " id INTEGER PRIMARY KEY AUTOINCREMENT, company TEXT, text TEXT, why TEXT, ts REAL)"
    )
    db.execute("CREATE INDEX IF NOT EXISTS decisions_by_company ON decisions (company, ts)")


def _migration_15(db: sqlite3.Connection) -> None:
    """Why a task exists, where a status change cannot erase it.

    `note` was carrying two jobs: the agent's reason for proposing the task, and
    the provenance of the last decision about it. Every caller of
    `set_task_status` overwrites it — "validated by CEO", "via console" — so the
    reason survived exactly until somebody acted on the task, which is the one
    moment it was needed. The operator was left with a row naming its own author
    and nothing else.
    """
    try:
        db.execute("ALTER TABLE tasks ADD COLUMN why TEXT")
    except sqlite3.OperationalError:
        pass  # already there: fresh stores get it from SCHEMA


def _migration_18(db: sqlite3.Connection) -> None:
    """Where a drafted answer came from, kept next to the action.

    `structured.ask` returns `ok`, `fell_back`, `attempts`, `source` and `errors`, and this
    table stored the boolean. Counted across the package: 12 callers read `.data`, 3 read
    `.ok`, 1 reads `.source`, 1 reads `.fell_back`, none read the other two. So after a turn,
    which provider answered and whether the chain fell back existed nowhere — and an operator
    read "Nothing usable drafted" as a broken site generator while two providers were
    answering 429, 365 026 tokens in.

    NULL on every existing row, and that is a third state the columns keep: **not recorded**
    is not the same answer as "no provider", and collapsing the two would make the console
    tell an operator their history says something it does not. Same reasoning as
    `_migration_16`'s `vision_ok`.
    """
    for column, kind in (
        ("source", "TEXT"),
        ("attempts", "INTEGER"),
        ("fell_back", "INTEGER"),
        ("errors", "TEXT"),
    ):
        try:
            db.execute(f"ALTER TABLE actions ADD COLUMN {column} {kind}")
        except sqlite3.OperationalError:
            pass


def _migration_17(db: sqlite3.Connection) -> None:
    """When each skill was last actually used, and how often.

    A skill reaches a prompt when the tool about to run is named in its `allowed-tools`, and
    until now that left no trace. Which is fine while an operator writes every skill by hand
    and can see the folder — and not fine at all once an *agent* can write one. Hermes Agent
    names the failure mode in its curator's own docstring: without maintenance you get
    "hundreds of narrow skills where each one captures one session's specific bug"
    (docs/reverse-engineering/hermes-agent.md).

    Here it would be worse than a cluttered folder. An unscoped skill rides on **every prompt
    of every turn**, and `SkillLoader.always_on_chars()` already exists to measure that tax.
    Shipping a writer without the counter that lets a curator archive what nobody reads would
    be building a leak next to its own gauge.

    Keyed by (company, skill) rather than by path: a company skill of the same name replaces a
    global one on purpose, and the count should follow the name the loader resolved.
    """
    db.execute(
        "CREATE TABLE IF NOT EXISTS skill_usage ("
        " company TEXT, skill TEXT, uses INTEGER DEFAULT 0, last_used REAL,"
        " PRIMARY KEY (company, skill))"
    )


# version -> callable(db). Applied in order for any version above the DB's own.
def _migration_16(db: sqlite3.Connection) -> None:
    """Whether a model can actually read an image, as opposed to claiming it can.

    The catalogue's word was never enough for JSON — one model in the owner's own
    fallback chain announces `structured_outputs` and cannot produce an object —
    and there is no reason to trust it here either. Measured on the live
    catalogue: 180 of 337 entries declare image input.

    NULL is a third state and the column keeps it: never asked. It is not the
    same answer as "cannot see", and collapsing the two would make the console
    tell an operator their model is blind because nobody has checked.
    """
    try:
        db.execute("ALTER TABLE model_probes ADD COLUMN vision_ok INTEGER")
    except sqlite3.OperationalError:
        pass  # already there: fresh stores get it from SCHEMA


MIGRATIONS = {
    1: _migration_1,
    2: _migration_2,
    3: _migration_3,
    4: _migration_4,
    5: _migration_5,
    6: _migration_6,
    7: _migration_7,
    8: _migration_8,
    9: _migration_9,
    10: _migration_10,
    11: _migration_11,
    12: _migration_12,
    13: _migration_13,
    14: _migration_14,
    15: _migration_15,
    16: _migration_16,
    17: _migration_17,
    18: _migration_18,
}
