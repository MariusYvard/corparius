"""The structured-output harness: the same shape out, whatever went in.

The point is provider-agnostic uniformity, so the tests feed the messy shapes
real models actually produce — clean JSON, JSON in a fence, prose wrapped around
JSON, a preamble, and total garbage — and assert one validated dict comes back
every time.
"""
import types

from app import structured
from app.models import LLMResult, Usage, Difficulty


SCHEMA = {
    "headline": {"type": "str", "required": True, "max_len": 20},
    "hashtags": {"type": "list", "default": []},
    "score": {"type": "int", "default": 0},
}


class FakeRouter:
    """Returns a scripted reply per call, so a repair round can be exercised."""
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = 0

    def generate(self, messages, difficulty=Difficulty.EASY, model=None, max_tokens=512):
        text = self.replies[min(self.calls, len(self.replies) - 1)]
        self.calls += 1
        return LLMResult(text=text, usage=Usage(10, 5), model="m", provider="fake")


def test_extract_survives_the_shapes_models_actually_return():
    clean = '{"headline": "hi"}'
    assert structured.extract_json(clean) == {"headline": "hi"}
    assert structured.extract_json('```json\n{"headline": "hi"}\n```') == {"headline": "hi"}
    assert structured.extract_json('Sure! Here you go:\n{"headline": "hi"}\nHope that helps!') == {"headline": "hi"}
    assert structured.extract_json("no json here at all") is None
    assert structured.extract_json("") is None


def test_validate_coerces_drops_and_defaults():
    obj = {"headline": "a very long headline that exceeds the cap", "hashtags": "solo",
           "score": "7", "extra": "dropped"}
    clean, errors = structured.validate(obj, SCHEMA)
    assert not errors
    assert len(clean["headline"]) <= 20
    assert clean["hashtags"] == ["solo"]      # a scalar becomes a one-item list
    assert clean["score"] == 7                # "7" coerced to int
    assert "extra" not in clean               # fields outside the schema are dropped


def test_missing_required_is_an_error():
    _clean, errors = structured.validate({"score": 1}, SCHEMA)
    assert any("headline" in e for e in errors)


def test_a_clean_json_reply_passes_first_try():
    r = structured.ask(FakeRouter(['{"headline": "Launch day", "score": 3}']), [], SCHEMA)
    assert r.ok and not r.fell_back and r.attempts == 1
    assert r.data["headline"] == "Launch day" and r.data["score"] == 3
    assert r.data["hashtags"] == []           # default filled


def test_a_bad_reply_is_repaired_on_the_retry():
    router = FakeRouter(["total garbage, no json", '{"headline": "Fixed"}'])
    r = structured.ask(router, [], SCHEMA, retries=1)
    assert r.ok and not r.fell_back and r.attempts == 2
    assert r.data["headline"] == "Fixed"
    assert len(r.usages) == 2                 # both calls are billed


def test_persistent_garbage_falls_back_but_still_returns_the_shape():
    router = FakeRouter(["nope", "still nope"])
    r = structured.ask(router, [], SCHEMA, retries=1)
    assert not r.ok and r.fell_back
    # The agent turn must survive: the shape is intact and the required field is
    # salvaged from the raw reply rather than left blank.
    assert set(r.data) >= {"headline", "hashtags", "score"}
    assert r.data["headline"]                 # non-empty, salvaged
    assert r.data["hashtags"] == [] and r.data["score"] == 0


def test_the_mock_provider_answers_structured_offline():
    # Offline mode must exercise the real structured path, not always fall back:
    # a homelab with no network still gets validated shapes.
    from app.llm import MockProvider
    router = types.SimpleNamespace(
        generate=lambda convo, diff=None, model=None, max_tokens=512:
            MockProvider().generate(convo, "gemma"))
    r = structured.ask(router, [{"role": "user", "content": "draft a post"}], SCHEMA)
    assert r.ok and not r.fell_back
    assert r.data["headline"] and isinstance(r.data["hashtags"], list)
