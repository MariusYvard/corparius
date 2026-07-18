"""A structured-output harness: the same shape out, whatever went in.

The provider layer already normalises the envelope (every provider returns an
LLMResult). This normalises the payload. Ask ten models to "draft a post" and you
get ten shapes: prose, JSON, JSON in a markdown fence, a preamble ("Sure! Here
is..."), a refusal disclaimer. An agent that slices `text[:120]` inherits all of
that noise. ask() makes the result a validated dict no matter which model, tier
or provider served the turn.

It works at the text level on purpose. The 14 free providers, Anthropic and the
Claude CLI each support "structured output" differently or not at all, so relying
on a provider feature would fragment exactly what this exists to unify. Instead:
instruct, extract, validate, repair once, then fall back to a deterministic
default so the agent turn always survives — the same bargain the router already
makes with slow local models.

The schema is a small dict, no jsonschema dependency (stdlib only, project ethos):

    {"headline": {"type": "str", "required": True, "max_len": 80},
     "hashtags": {"type": "list", "default": []},
     "tone":     {"type": "str", "choices": ["plain", "bold"], "default": "plain"}}
"""
from __future__ import annotations
import json
import re
from dataclasses import dataclass, field

_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.S | re.I)


@dataclass
class Result:
    data: dict
    ok: bool                     # a model produced valid structure (not the fallback)
    attempts: int
    source: str = ""             # "provider:model" that answered, for the log
    raw: str = ""
    errors: list[str] = field(default_factory=list)
    fell_back: bool = False
    # Every LLM call the harness made, including repair rounds, so the caller
    # bills all of them and no token spent goes unaccounted.
    usages: list = field(default_factory=list)


def extract_json(text: str) -> dict | None:
    """The first JSON object in a reply, stripped of markdown fences and any
    prose a chatty model wrapped around it."""
    if not text:
        return None
    fenced = _FENCE.search(text)
    candidates = []
    if fenced:
        candidates.append(fenced.group(1).strip())
    candidates.append(text.strip())
    depth = start = 0            # also try the first balanced {...} run
    for i, ch in enumerate(text):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}" and depth:
            depth -= 1
            if depth == 0:
                candidates.append(text[start:i + 1])
                break
    for c in candidates:
        try:
            obj = json.loads(c)
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(obj, dict):
            return obj
    return None


def _coerce_one(key: str, spec: dict, value):
    want = spec.get("type", "str")
    if value is None:
        raise ValueError(f"{key}: missing")
    if want == "str":
        out = value if isinstance(value, str) else json.dumps(value) if isinstance(value, (dict, list)) else str(value)
        out = out.strip()
        if "max_len" in spec:
            out = out[:spec["max_len"]].rstrip()
        if spec.get("choices") and out not in spec["choices"]:
            raise ValueError(f"{key}: '{out}' not one of {spec['choices']}")
        if not out and spec.get("required"):
            raise ValueError(f"{key}: empty")
        return out
    if want == "int":
        return int(value)
    if want == "float":
        return float(value)
    if want == "bool":
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in ("true", "1", "yes")
    if want == "list":
        seq = value if isinstance(value, list) else [value]
        return [str(v).strip() for v in seq if str(v).strip()]
    return value


def validate(obj: dict, schema: dict) -> tuple[dict, list[str]]:
    """Coerce every field to its spec. Returns (clean, errors). Fields not in the
    schema are dropped: uniform shape means the shape the schema names, nothing a
    model decided to add."""
    clean, errors = {}, []
    for key, spec in schema.items():
        if key in obj and obj[key] is not None:
            try:
                clean[key] = _coerce_one(key, spec, obj[key])
                continue
            except (ValueError, TypeError) as exc:
                errors.append(str(exc))
        if spec.get("required"):
            errors.append(f"{key}: required")
        elif "default" in spec:
            clean[key] = spec["default"]
    return clean, errors


def defaults(schema: dict) -> dict:
    out = {}
    for key, spec in schema.items():
        if "default" in spec:
            out[key] = spec["default"]
        elif spec.get("type") == "list":
            out[key] = []
        else:
            out[key] = "" if spec.get("type", "str") == "str" else 0
    return out


def render_hint(schema: dict) -> str:
    """A compact shape the model can copy, e.g.
    {"headline": "string (<=80 chars)", "hashtags": ["string", ...]}."""
    parts = []
    for key, spec in schema.items():
        want = spec.get("type", "str")
        if want == "list":
            shape = '["string", ...]'
        elif want in ("int", "float"):
            shape = "number"
        elif want == "bool":
            shape = "true|false"
        elif spec.get("choices"):
            shape = "|".join(spec["choices"])
        else:
            shape = "string" + (f" (<={spec['max_len']} chars)" if "max_len" in spec else "")
        req = "" if spec.get("required") else " (optional)"
        parts.append(f'  "{key}": {shape}{req}')
    return "{\n" + ",\n".join(parts) + "\n}"


# Marker the schema-aware MockProvider recognises so offline mode produces real
# structured output instead of always taking the fallback path.
MARKER = "<<corp-json-schema>>"


def instruction(schema: dict) -> str:
    return (f"{MARKER}\nReturn only a JSON object matching this shape, with no prose, "
            f"no explanation and no markdown fence:\n{render_hint(schema)}")


def ask(router, messages: list[dict], schema: dict, difficulty=None,
        *, retries: int = 1, fallback: dict | None = None) -> Result:
    """Drive the router until the reply validates, then stop. On exhaustion,
    return the fallback (or the schema defaults) so the caller always gets the
    agreed shape and the agent turn never dies on a malformed reply."""
    from .models import Difficulty
    difficulty = difficulty or Difficulty.EASY
    convo = list(messages)
    convo.append({"role": "user", "content": instruction(schema)})
    last_raw, last_errors, source, usages = "", [], "", []
    for attempt in range(1, retries + 2):
        res = router.generate(convo, difficulty)
        usages.append(res.usage)
        last_raw = res.text
        source = f"{res.provider}:{res.model}"
        obj = extract_json(res.text)
        if obj is not None:
            clean, errors = validate(obj, schema)
            if not errors:
                return Result(clean, ok=True, attempts=attempt, source=source,
                              raw=res.text, usages=usages)
            last_errors = errors
        else:
            last_errors = ["no JSON object in the reply"]
        # Correct and try again with the same tier.
        convo.append({"role": "assistant", "content": res.text[:500]})
        convo.append({"role": "user",
                      "content": f"That did not match. {', '.join(last_errors)}. "
                                 f"Return only the JSON:\n{render_hint(schema)}"})
    data = dict(fallback) if fallback else defaults(schema)
    # Salvage whatever a required string needs from the raw reply, so the fallback
    # is not blank when a model gave prose instead of JSON.
    for key, spec in schema.items():
        if spec.get("required") and not data.get(key) and spec.get("type", "str") == "str":
            snippet = re.sub(r"\s+", " ", last_raw).strip()
            data[key] = snippet[:spec.get("max_len", 120)] or key
    clean, _ = validate(data, schema)
    return Result(clean, ok=False, attempts=retries + 1, source=source,
                  raw=last_raw, errors=last_errors, fell_back=True, usages=usages)
