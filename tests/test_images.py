"""A picture in the company's folder has to actually reach a model.

For two releases the product said an image was "offered to the models that accept
images" — in the module docstring, in the console badge in both languages, in
docs/documents.md and in the README. None of it was true: `documents.images()` had
no caller anywhere, no capability signal existed, and nothing in llm.py, agents.py
or structured.py could have sent one. The image was listed, named, and dropped.

Nothing failed, because nothing was watching. So the first test here is the one
that was missing: the claim is pinned to a code path, and if the path goes away the
sentence cannot survive it.
"""

import struct
import zlib

import pytest

from corparius import documents
from corparius.agents import Executor
from corparius.kernel.records import AgentRole, Difficulty, LLMResult, Usage
from corparius.providers import llm, preflight
from corparius.roster import ROSTER
from corparius.tools.registry import TOOLS

# --- the guard that was missing ----------------------------------------------


def test_nothing_may_claim_a_model_sees_an_image_unless_a_path_sends_one():
    """The test that would have caught it, kept deliberately blunt.

    Every surface that tells an operator a picture reaches a model — the module,
    the console in both languages, the docs, the README — is only allowed to say
    so while the wiring exists: `documents.images()` has a caller, the provider
    contract carries images, and a tool can ask for them.
    """
    from pathlib import Path

    # `rglob`, not `glob`: the flat spelling stops seeing a caller the moment it moves into
    # a subpackage, and this assertion would then pass for the wrong reason — it exists
    # precisely because `documents.images()` once had no caller at all for two releases.
    root = Path("corparius")
    callers = [
        p.relative_to(root).as_posix()
        for p in root.rglob("*.py")
        if p.name != "documents.py" and "documents.images(" in p.read_text(encoding="utf-8")
    ]
    assert callers, "documents.images() has no caller: nothing can send a picture"

    import inspect

    assert "images" in inspect.signature(llm.LLMProvider.generate).parameters, (
        "the provider contract cannot carry a picture"
    )
    assert "images" in inspect.signature(llm.HybridRouter.generate).parameters, (
        "the router cannot carry a picture"
    )
    assert hasattr(llm, "read_images"), "no loader, so no picture can be carried"
    assert any(getattr(t, "sees_images", False) for t in TOOLS.values()), (
        "no tool asks for a picture, so none is ever sent"
    )


# --- the probe image ----------------------------------------------------------


def test_the_probe_image_is_a_real_decodable_png():
    """Built in code rather than shipped as a binary fixture, so it has to be
    checked like one: a decoder validates the CRCs before anything else."""
    png = preflight.vision_png()
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    width, height = struct.unpack(">II", png[16:24])
    assert (width, height) == (8, 16) and png[24] == 8 and png[25] == 2

    index, tags = 8, []
    while index < len(png):
        length = struct.unpack(">I", png[index : index + 4])[0]
        body = png[index + 4 : index + 8 + length]
        crc = struct.unpack(">I", png[index + 8 + length : index + 12 + length])[0]
        assert crc == zlib.crc32(body), f"bad CRC on {body[:4]!r}"
        tags.append(body[:4].decode())
        index += 12 + length
    assert tags == ["IHDR", "IDAT", "IEND"]


def test_the_probe_never_names_the_answer_it_expects():
    """Two colours rather than one, because one is a question a model that sees
    nothing answers correctly by guessing — and neither of them written in the
    prompt, because a prompt that names the answer is a prompt a blind model can
    pass by echoing it. Both halves of that matter, so both are pinned."""
    assert preflight.VISION_TOP != preflight.VISION_BOTTOM
    said = preflight.VISION_PROMPT.lower()
    assert preflight.VISION_TOP not in said, "the prompt gives away the top colour"
    assert preflight.VISION_BOTTOM not in said, "the prompt gives away the bottom colour"
    assert "two words" in said, "one word cannot carry an ordered pair"


def _reply(text: str):
    class Response:
        status_code = 200

        @staticmethod
        def json():
            return {"choices": [{"message": {"content": text}}]}

    return Response()


@pytest.mark.parametrize(
    "answer,verdict",
    [
        ("blue yellow", True),
        ("Blue, Yellow.", True),
        ("yellow blue", False),  # read the prompt, not the picture
        ("blue", False),
        ("I cannot see images", False),
    ],
)
def test_the_verdict_needs_both_colours_the_right_way_round(monkeypatch, answer, verdict):
    monkeypatch.setenv("GROQ_API_KEY", "k")
    from corparius.config import cfg

    cfg.invalidate()
    monkeypatch.setattr(preflight.requests, "post", lambda *a, **k: _reply(answer))
    assert preflight.vision_probe("groq", "m") is verdict


def test_a_transport_failure_is_not_a_verdict(monkeypatch):
    """None, not False. Marking a model blind because a laptop was on a train is
    a measurement of the network."""
    monkeypatch.setenv("GROQ_API_KEY", "k")
    from corparius.config import cfg

    cfg.invalidate()

    def boom(*a, **k):
        raise preflight.requests.ConnectionError("offline")

    monkeypatch.setattr(preflight.requests, "post", boom)
    assert preflight.vision_probe("groq", "m") is None


# --- loading and bounding ----------------------------------------------------


def test_what_cannot_be_sent_is_named_with_its_real_size(tmp_path):
    """ "No silent truncation" covers a dropped picture as much as a cut document."""
    small = tmp_path / "ok.png"
    small.write_bytes(preflight.vision_png())
    huge = tmp_path / "huge.png"
    huge.write_bytes(preflight.vision_png() + b"\x00" * 2048)
    text = tmp_path / "notes.md"
    text.write_text("not a picture", encoding="utf-8")

    carried, skipped = llm.read_images([small, huge, text], max_bytes=1024)
    assert [i.name for i in carried] == ["ok.png"]
    joined = " ".join(skipped)
    assert "huge.png" in joined and "1024" in joined and str(huge.stat().st_size) in joined
    assert "notes.md" in joined


def test_the_per_call_limit_is_said_not_silently_applied(tmp_path):
    paths = []
    for i in range(4):
        path = tmp_path / f"s{i}.png"
        path.write_bytes(preflight.vision_png())
        paths.append(path)
    carried, skipped = llm.read_images(paths, limit=2)
    assert len(carried) == 2
    assert len(skipped) == 2 and all("limit" in s for s in skipped)


def test_a_file_that_disappeared_is_a_line_of_prose_not_an_exception(tmp_path):
    missing = tmp_path / "gone.png"
    carried, skipped = llm.read_images([missing])
    assert carried == [] and len(skipped) == 1 and "gone.png" in skipped[0]


# --- each provider's own dialect ---------------------------------------------


def _sent(monkeypatch, provider, method="post"):
    """Capture the payload a provider would put on the wire."""
    seen: dict = {}

    class Response:
        status_code = 200

        @staticmethod
        def raise_for_status():
            return None

        @staticmethod
        def json():
            return {
                "choices": [{"message": {"content": "ok"}}],
                "content": [{"text": "ok"}],
                "message": {"content": "ok"},
                "usage": {},
            }

    def capture(*args, **kwargs):
        seen.update(kwargs.get("json") or {})
        if kwargs.get("data"):
            import json as _json

            seen.update(_json.loads(kwargs["data"]))
        return Response()

    monkeypatch.setattr(llm.requests, method, capture)
    return seen


ONE = [llm.Image(b"\x89PNG", "image/png", "shot.png")]
TURN = [{"role": "system", "content": "sys"}, {"role": "user", "content": "look"}]


def test_the_openai_dialect_sends_a_data_uri(monkeypatch):
    seen = _sent(monkeypatch, "openai")
    llm.OpenAICompatProvider("groq", "https://x/v1", "k").generate(TURN, "m", 64, ONE)
    content = seen["messages"][-1]["content"]
    assert content[0] == {"type": "text", "text": "look"}
    assert content[1]["image_url"]["url"].startswith("data:image/png;base64,")


def test_the_anthropic_dialect_sends_a_source_block(monkeypatch):
    seen = _sent(monkeypatch, "anthropic")
    llm.AnthropicProvider("k").generate(TURN, "m", 64, ONE)
    blocks = seen["messages"][-1]["content"]
    assert blocks[0]["type"] == "image"
    assert blocks[0]["source"]["type"] == "base64"
    assert blocks[0]["source"]["media_type"] == "image/png"
    # The system turns are still joined as strings, which is why images never go
    # into `messages` as blocks by default.
    assert seen["system"] == "sys"


def test_the_ollama_dialect_sends_bare_base64(monkeypatch):
    seen = _sent(monkeypatch, "ollama")
    llm.OllamaProvider("http://x", "e").generate(TURN, "m", 64, ONE)
    turn = seen["messages"][-1]
    assert turn["images"] == [ONE[0].b64]
    assert "data:" not in turn["images"][0], "Ollama takes no data: prefix"
    assert turn["content"] == "look", "content stays a string in this dialect"


def test_a_text_only_call_keeps_string_content(monkeypatch):
    """The contract the whole module depends on: `_flatten`, the mock and
    Anthropic's system join all read `content` as a string."""
    seen = _sent(monkeypatch, "openai")
    llm.OpenAICompatProvider("groq", "https://x/v1", "k").generate(TURN, "m", 64)
    assert all(isinstance(m["content"], str) for m in seen["messages"])


# --- who is allowed to receive one -------------------------------------------


class _Legacy(llm.LLMProvider):
    """A provider written before images existed, as a plugin may well be."""

    name = "legacy"

    def generate(self, messages, model, max_tokens=512):
        return LLMResult(text="ok", usage=Usage(1, 1), model=model, provider=self.name)


def test_a_provider_written_before_images_is_never_handed_one():
    """corparius/plugins.py lets a plugin register its own provider. A fourth
    positional argument would break it on the first turn."""
    assert llm.HybridRouter._carry(_Legacy(), ONE) == {}
    assert llm.HybridRouter._carry(llm.MockProvider(), ONE) == {"images": ONE}


def test_claude_code_declares_that_it_carries_none():
    """It takes a prompt on argv; there is no shape for a picture. Declared, so
    the router does not hand it one it would have to drop."""
    assert llm.ClaudeCodeProvider.accepts_images is False


# --- the three conditions ----------------------------------------------------


def _executor(monkeypatch, mock=True):
    from corparius.config.settings import Settings

    settings = Settings()
    monkeypatch.setattr(settings, "llm_mock", mock, raising=False)
    router = llm.HybridRouter(settings)
    monkeypatch.setattr(router, "settings", settings, raising=False)
    return Executor(router, None, None, settings)


def test_a_tool_that_never_asked_receives_nothing(monkeypatch):
    """A capture helps a design brief and does nothing for reconciling Stripe."""
    import types

    ex = _executor(monkeypatch)
    ctx = types.SimpleNamespace(company={"slug": "t"}, store=None, images=ONE)
    assert ex._pictures_for(TOOLS["reconcile_stripe"], ROSTER[AgentRole.FINANCE], ctx) == []
    assert ex._pictures_for(TOOLS["draft_design_brief"], ROSTER[AgentRole.DESIGN], ctx) == ONE


def test_the_tools_that_ask_are_the_ones_whose_job_is_visual():
    asking = sorted(name for name, t in TOOLS.items() if getattr(t, "sees_images", False))
    assert asking == [
        "draft_design_brief",
        # The two reviews, which judged pages they had never seen. `_site_text` strips the tags and
        # sends the prose, which is the right input for wording and says nothing about contrast,
        # hierarchy, or whether the first screen names what is being sold.
        "review_generated_site",
        "review_site",
        "scan_competitors",
    ]


def test_only_the_reviews_take_their_own_picture():
    """`shoots_site` is the stronger claim and a much shorter list.

    `sees_images` offers what is already on file; this renders the company's own pages with a
    browser, which costs a couple of seconds each. A design brief is helped by a competitor's
    screenshot the operator dropped in and has no business making corparius launch a browser, so the
    two flags are deliberately not the same set.
    """
    shooting = sorted(name for name, t in TOOLS.items() if getattr(t, "shoots_site", False))
    assert shooting == ["review_generated_site", "review_site"]
    for name in shooting:
        assert TOOLS[name].sees_images, f"{name} takes a picture nothing would send"


def test_the_flag_cannot_be_set_on_a_tool_that_calls_no_model():
    """`sees_images` is only ever read on the drafting path, so setting it on a
    tool with `needs_draft=False` does nothing — silently.

    `produce_mockup` is the trap: it is the design agent's obviously visual job
    and it makes no model call at all, so it would look wired and never be. A
    dead flag reads as a feature to the next person who greps for it.
    """
    dead = sorted(
        name
        for name, tool in TOOLS.items()
        if getattr(tool, "sees_images", False) and not tool.needs_draft
    )
    assert not dead, f"these declare sees_images but call no model, so it is never read: {dead}"


def test_a_model_with_no_verdict_and_no_claim_gets_nothing(monkeypatch):
    """Neither measured nor declared means not sent: a picture mailed to a
    text-only model is paid for and thrown away by the provider."""
    import types

    ex = _executor(monkeypatch, mock=False)
    ctx = types.SimpleNamespace(company={"slug": "t"}, store=None, images=ONE)
    assert ex._pictures_for(TOOLS["draft_design_brief"], ROSTER[AgentRole.DESIGN], ctx) == []


def test_the_measured_verdict_outranks_the_catalogue(monkeypatch, tmp_path):
    """This project already knows what a capability claim is worth."""
    import types

    from corparius.providers import modelinfo
    from corparius.store import Store

    store = Store(str(tmp_path))
    ex = _executor(monkeypatch, mock=False)
    model = ex.router.resolve_model(Difficulty.EASY, None)
    _, name = llm.split_target(model)

    # The catalogue says yes...
    monkeypatch.setattr(
        modelinfo, "cached", lambda s: {modelinfo._normalise(name): {"vision": True}}
    )
    ctx = types.SimpleNamespace(company={"slug": "t"}, store=store, images=ONE)
    assert ex._pictures_for(TOOLS["draft_design_brief"], ROSTER[AgentRole.DESIGN], ctx) == ONE

    # ...and a real call proved otherwise, which wins.
    store.record_measurement("groq", name, 10.0, True, 1, 0, vision_ok=False)
    assert ex._pictures_for(TOOLS["draft_design_brief"], ROSTER[AgentRole.DESIGN], ctx) == []
    store.close()


def test_never_asked_is_not_the_same_stored_answer_as_cannot_see(tmp_path):
    """NULL is a third state, and a later measurement that did not ask must not
    erase a verdict an earlier one got."""
    from corparius.store import Store

    store = Store(str(tmp_path))
    store.record_measurement("p", "unasked", 1.0, True, 1, 0)
    store.record_measurement("p", "seer", 1.0, True, 1, 0, vision_ok=True)
    store.record_measurement("p", "seer", 2.0, True, 1, 0)  # no vision this time
    rows = {r["model"]: r["vision_ok"] for r in store.known_probes()}
    assert rows["unasked"] is None
    assert rows["seer"] == 1
    store.close()


# --- the operator's right to refuse ------------------------------------------


def test_zero_means_never_and_is_the_reason_this_is_a_setting(tmp_path, monkeypatch):
    """A document's text is extracted on this machine. A picture has to leave it to
    be read, and a screenshot may hold a customer's data.

    Before this setting the only refusal available was turning every cloud
    provider off, which also gives up the text — so there was no way to keep cloud
    text and decline cloud pictures, the more sensitive of the two.
    """
    from corparius.config.settings import Settings

    monkeypatch.setenv("CORP_IMAGE_MAX_PER_CALL", "0")
    from corparius.config import cfg

    cfg.invalidate()
    assert Settings().image_max_per_call == 0

    monkeypatch.setenv("CORP_IMAGE_MAX_PER_CALL", "1")
    cfg.invalidate()
    assert Settings().image_max_per_call == 1
    # And the cap it feeds is honoured, not merely stored.
    paths = []
    for i in range(3):
        path = tmp_path / f"s{i}.png"
        path.write_bytes(preflight.vision_png())
        paths.append(path)
    carried, skipped = llm.read_images(paths, limit=Settings().image_max_per_call)
    assert len(carried) == 1 and len(skipped) == 2


def test_the_refusal_is_in_the_registry_so_the_console_shows_it():
    """A privacy control an operator cannot find is a control they do not have."""
    from corparius.config.settings_spec import BY_KEY, WRITABLE

    row = BY_KEY.get("CORP_IMAGE_MAX_PER_CALL")
    assert row is not None, "the setting is not in the registry, so the console cannot write it"
    assert row.type == "int" and row.default == "2"
    assert "CORP_IMAGE_MAX_PER_CALL" in WRITABLE, "the console would refuse to save it"
    # Both languages, and both have to say what zero does — a control whose off
    # position is undocumented is a control nobody uses.
    assert "0" in row.help_en and "0" in row.help_fr
    assert row.label_en and row.label_fr


# --- reaching the capability without wrecking the rest ------------------------


def test_a_role_can_be_pinned_to_its_own_model(tmp_path):
    """The capability was unreachable by configuration.

    Only three tiers are settable and nine of the ten roles take theirs from one
    of them, so giving the design agent a model that reads pictures meant moving
    the whole normal tier. Measured on a real configuration: 535 tok/s down to 49
    across the CEO, outreach, support and design, to gain vision on one of them.
    The only other route was editing agents.py, which is not configuration.
    """
    from corparius.orchestrator import model_overrides
    from corparius.store import Store

    store = Store(str(tmp_path))
    store.add_directive("acme", "model", "design", "openrouter:nvidia/nemotron-omni:free")
    assert model_overrides(store, "acme") == {"design": "openrouter:nvidia/nemotron-omni:free"}
    store.close()


@pytest.mark.parametrize(
    "pinned,accepted",
    [
        ("groq:llama-3.3-70b-versatile", True),
        ("openrouter:nvidia/nemotron-omni:free", True),  # a colon inside the name
        ("local:gemma4:e4b", True),
        ("cloud:claude-opus-5", True),
        ("opnerouter:typo", False),  # the typo this exists to catch
        ("gemma4:e4b", False),  # a bare Ollama tag: say local:
        ("groq:", False),
        ("", False),
    ],
)
def test_a_pin_must_name_a_target_this_build_routes_to(pinned, accepted):
    """`split_target` defaults an unknown prefix to local, on purpose, so that a bare
    Ollama tag works in the tier settings. That makes `opnerouter:typo` and
    `gemma4:e4b` the same shape to it — both come back local — so validating a pin
    through `split_target` would accept the typo and send every turn of that role to
    Ollama, which reads as a slow day rather than as a mistake.

    A pin therefore spells its target out, and the refusal is reported.
    """
    from corparius.orchestrator import _known_target

    assert _known_target(pinned) is accepted


def test_a_refused_pin_is_not_stored_as_a_working_one(tmp_path):
    from corparius.orchestrator import model_overrides
    from corparius.store import Store

    store = Store(str(tmp_path))
    store.add_directive("acme", "model", "design", "opnerouter:typo")
    store.add_directive("acme", "model", "social", "groq:llama-3.3-70b-versatile")
    assert model_overrides(store, "acme") == {"social": "groq:llama-3.3-70b-versatile"}
    store.close()


def test_pinning_one_role_leaves_the_others_on_their_tier():
    """The whole reason this is per role: the other three EASY roles must not be
    dragged onto a model ten times slower to give one of them eyes."""
    from dataclasses import replace as _replace

    design = _replace(ROSTER[AgentRole.DESIGN], model="openrouter:seer:free")
    assert design.model == "openrouter:seer:free"
    # The shared roster entry is untouched, or every company in the process would
    # inherit the pin — the console runs several.
    assert ROSTER[AgentRole.DESIGN].model is None
    for role in (AgentRole.CEO, AgentRole.OUTREACH, AgentRole.SUPPORT):
        assert ROSTER[role].model is None


# --- end to end, offline -----------------------------------------------------


def test_a_dropped_picture_reaches_a_real_model_call(tmp_path, monkeypatch):
    """The whole point, asked of the wiring rather than of the documentation."""
    monkeypatch.setenv("CORP_HOME", str(tmp_path))
    monkeypatch.setenv("CORP_LLM_MOCK", "true")
    from corparius.config import cfg

    cfg.invalidate()
    folder = tmp_path / "companies" / "acme" / "documents"
    folder.mkdir(parents=True)
    (folder / "rival.png").write_bytes(preflight.vision_png())

    carried, _ = llm.read_images(documents.images("acme"))
    assert [i.name for i in carried] == ["rival.png"]

    import types

    ex = _executor(monkeypatch)
    ctx = types.SimpleNamespace(
        company={"slug": "acme", "name": "Acme"},
        store=None,
        images=carried,
        documents="",
        skills=None,
    )
    pictures = ex._pictures_for(TOOLS["draft_design_brief"], ROSTER[AgentRole.DESIGN], ctx)
    result = ex.router.generate([{"role": "user", "content": "look"}], images=pictures)
    assert "saw 1 image(s): rival.png" in result.text
