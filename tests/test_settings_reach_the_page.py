"""A setting that exists and does not show up is a setting that does not exist.

This file was written because of a question an operator actually asked: "why do I not see Qonto in
the settings?" The fields were declared, the validation accepted them, the provider module read
them, and the console showed nothing. Every part worked and the feature did not, which is the shape
this codebase keeps finding and keeps testing both ends of.

There are three joints between "declared" and "rendered", and each one is somewhere a field can fall
through in silence:

  * `SPEC` -> `settings_payload()["fields"]`, which is what the page fetches;
  * a field's `group` -> a name in `GROUPS`, because the page renders group by group and a field
    whose group does not exist has nowhere to be drawn;
  * `GROUPS` -> the payload, so a group cannot be declared and left out of what the page receives.

None of these raise. A mistyped group name is a valid string, the payload is still valid JSON, the
page still renders, and the field is simply absent from a screen nobody can diff against a registry
in their head. So they are asserted rather than trusted, and asserted generically: a test naming
only Qonto would pass for the next credential and fail the same operator again.
"""

from corparius.api import adapters
from corparius.config import settings_spec


def _payload() -> dict:
    """No `UiState` and no store: `settings_payload` is pure description, and the fact that it can
    be called with nothing is itself worth pinning. A payload that needed a live console to build
    would be one more reason for this test not to exist."""
    return adapters.settings_payload()


def test_every_declared_field_reaches_the_payload():
    """The first joint. `SPEC` is the registry and `fields` is what the page gets, so the two are
    the same set or something declared is invisible."""
    payload = _payload()
    delivered = {f["key"] for f in payload["fields"]}
    declared = {f.key for f in settings_spec.SPEC}
    assert declared - delivered == set(), (
        f"declared and never delivered to the console: {sorted(declared - delivered)}"
    )
    assert delivered - declared == set(), (
        f"delivered without a registry entry, so nothing coerces it: {sorted(delivered - declared)}"
    )


def test_every_field_belongs_to_a_group_the_page_draws():
    """The second joint, and the one that is invisible to every other test. A field carrying a group
    name with a typo in it is a valid field: it validates, it stores, it reads back, and it is drawn
    nowhere because the page loops over `GROUPS` and asks each one for its fields."""
    payload = _payload()
    known = {g["name"] for g in payload["groups"]}
    orphans = sorted(
        f["key"] for f in payload["fields"] if f.get("group") and f["group"] not in known
    )
    assert not orphans, (
        f"these have a group that is not in GROUPS, so they render nowhere: {orphans}"
    )


def test_every_group_carries_a_field():
    """The other end of the same thread. An empty group draws a heading and a help paragraph over
    nothing, which reads as a section that failed to load rather than one that is not needed."""
    payload = _payload()
    used = {f.get("group") for f in payload["fields"]}
    empty = sorted(g["name"] for g in payload["groups"] if g["name"] not in used)
    assert not empty, f"declared groups with no field under them: {empty}"


def test_both_ways_of_being_paid_are_in_the_payments_section():
    """The specific case that prompted the file, kept alongside the general rules rather than
    instead of them. Stripe and Qonto answer different halves of a French business (a stranger
    clicking a link, and a client transferring against an invoice) and an operator who can only find
    one of them has half a product."""
    fields = {f["key"]: f for f in _payload()["fields"]}
    for key in ("STRIPE_API_KEY", "QONTO_LOGIN", "QONTO_SECRET_KEY"):
        assert key in fields, f"{key} never reaches the settings screen"
        assert fields[key]["group"] == "payments", f"{key} is drawn under {fields[key]['group']}"


def test_the_payments_heading_names_what_is_under_it():
    """The version of "not visible" that has nothing to do with the payload.

    The fields were in the section and the section said "Stripe.", so an operator scanning headings
    for their bank had no reason to open it. A group's help text is the only description of the
    group a person reads, and one that names a subset of what it holds hides the rest as effectively
    as a missing field.
    """
    payments = next(g for g in _payload()["groups"] if g["name"] == "payments")
    for lang in ("help_en", "help_fr"):
        said = payments[lang].lower()
        assert "stripe" in said and "qonto" in said, (
            f"{lang} names one of the two: {payments[lang]}"
        )


def test_a_secret_is_never_sent_back_with_its_value():
    """Not the subject of this file, and checked here anyway because this is the payload that goes
    to a browser, and the Qonto work added a field to it.

    The rule is narrower than "never send values", which is what a first pass asserted and which is
    wrong: the console has to draw the current host and port, so a non-secret field carries its
    value and must. What must not travel is a field the registry marks `secret`. Those come back as
    `None`, and the screen reports whether a key is set from a separate flag, because a console that
    round-trips secrets turns every read of the page into a way to collect them.
    """
    for field in _payload()["fields"]:
        if field.get("secret"):
            assert field.get("value") is None, f"{field['key']} ships its secret to the page"

    # And the pair that arrived with Qonto, named rather than left to the loop: the secret key is
    # secret and the login is not, deliberately. A login is an identifier, and showing it back is
    # how an operator confirms which account is connected rather than guessing.
    fields = {f["key"]: f for f in _payload()["fields"]}
    assert fields["QONTO_SECRET_KEY"]["secret"] is True
    assert fields["QONTO_LOGIN"]["secret"] is False
