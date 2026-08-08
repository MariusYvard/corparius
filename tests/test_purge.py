"""Purging a company drops everything about it, and it did not.

`purge_company`'s docstring says "drop everything recorded for one company". It listed six
tables. The schema had grown to **thirteen** with a `company` column, so seven survived:

    decisions  directives  drafts  inbox  memory  rules  skill_usage

`memory` is the company's durable facts and `drafts` is everything it wrote, so the purge was
not the deletion an operator asked for. But `rules` is the one that mattered: it holds
"approve, and stop asking", up to WRITE_REMOTE. A company purged and recreated under the same
slug **inherited standing authorisations the operator granted a different company** — a
permission surviving the thing it was about.

The list is derived from the schema now. A hardcoded thirteen would rot exactly as the six did,
and this file is what makes the derivation honest: it asks the database which tables are
company-scoped and requires every one of them to be emptied.
"""

import pytest

from corparius.store import Store


@pytest.fixture()
def store(tmp_path):
    s = Store(str(tmp_path / "data"))
    yield s
    s.close()


def _fill(store, slug):
    """One row in as many company-scoped tables as there are public writers for."""
    store.record_action(slug, "ceo", "decide", {}, "done", True)
    store.record_usage(slug, "ceo", 10, 5)
    store.save_state(slug, {"tick": 3})
    store.remember(slug, "ceo", f"un fait pour {slug}")
    store.add_task(slug, "une tâche", "social", 3, created_by="ceo")
    store.add_rule(slug, "send_outreach", "always", "granted by the operator")
    store.add_directive(slug, "pause", "social", "asked in the chat")
    store.add_decision(slug, "on garde le prix", "mesuré")
    store.add_draft(slug, "post", "linkedin", "un brouillon")
    store.record_skill_use(slug, ["une-competence"])
    from corparius import inbox

    inbox.notify(store, slug, "ceo", "Quelque chose à voir", "le corps")


# --- the derivation -------------------------------------------------------------


def test_the_scoped_tables_are_asked_of_the_schema(store):
    """Thirteen today. The number is not asserted — the *source* is, because a list in the code
    is what drifted from the schema in the first place."""
    scoped = store.company_tables()
    assert len(scoped) >= 13, f"only {len(scoped)} company-scoped tables found: {scoped}"
    for expected in ("memory", "rules", "drafts", "decisions", "directives", "inbox", "actions"):
        assert expected in scoped, f"{expected} has a company column and is not in the list"


def test_nothing_without_a_company_column_is_in_the_list(store):
    """`machine`, `model_probes`, `model_catalogue` and `settings` are not per-company. Deleting
    from them on a purge would take the operator's measured hardware profile and their API keys
    with the company."""
    scoped = set(store.company_tables())
    for global_table in ("machine", "model_probes", "model_catalogue", "settings"):
        assert global_table not in scoped, f"{global_table} is not per-company"


# --- the purge ------------------------------------------------------------------


def test_every_company_scoped_table_is_emptied(store):
    """The assertion the six-name list would have failed. Derived on both sides, so a table
    added tomorrow is covered without anybody remembering this file."""
    _fill(store, "acme")
    store.purge_company("acme")
    left = {}
    for table in store.company_tables():
        rows = store.db.execute(
            f"SELECT COUNT(*) n FROM {table} WHERE company=?", ("acme",)
        ).fetchone()["n"]
        if rows:
            left[table] = rows
    assert not left, f"these tables still hold rows for a purged company: {left}"


def test_a_standing_permission_does_not_survive_the_company(store):
    """The one that made this a safety fix rather than a tidiness one. "Approve, and stop
    asking" outliving the company it was about means a new company on the same slug starts with
    authorisations nobody granted it."""
    store.add_rule("acme", "send_outreach", "always", "granted by the operator")
    assert store.find_rule("acme", "send_outreach"), "the rule should exist first"
    store.purge_company("acme")
    assert not store.find_rule("acme", "send_outreach"), (
        "a standing permission survived the purge; a company recreated on this slug would "
        "inherit it"
    )


def test_the_durable_memory_goes_with_it(store):
    """The most substantive thing a company owns, and it was surviving a deletion."""
    store.remember("acme", "ceo", "un fait qui doit disparaître")
    assert store.list_memory("acme")
    store.purge_company("acme")
    assert store.list_memory("acme") == []


def test_another_company_is_untouched(store):
    """The purge is scoped by slug, and this is the assertion that keeps a derived table list
    from becoming a derived `DELETE FROM everything`."""
    _fill(store, "acme")
    _fill(store, "other")
    store.purge_company("acme")
    assert store.list_memory("other"), "another company lost its memory"
    assert store.list_tasks("other"), "another company lost its backlog"
    assert store.find_rule("other", "send_outreach"), "another company lost its permissions"


def test_it_reports_what_it_removed(store):
    """The console shows this back to the operator. A count of six tables when thirteen were
    scoped was also a report that understated what had happened — or overstated it, depending
    on which way you read a table that was never touched."""
    _fill(store, "acme")
    removed = store.purge_company("acme")
    assert set(removed) == set(store.company_tables())
    assert removed["memory"] >= 1 and removed["rules"] >= 1
