"""Reading and writing a .env file. Rank 0: pure.

Both halves lived far apart and for bad reasons. `parse` was inside `cfg`, which is where
it is *used*, but a parser has no business knowing about settings layers. `merge` was inside
`webui.py` — a thirty-line dotenv writer at the bottom of a 2 468-line HTTP server — which
is the only reason an archive utility imported the console.

They belong together, and here, because the security property below is about the pair: what
`merge` refuses is exactly what would let `parse` read back a line nobody wrote.
"""

from __future__ import annotations

from pathlib import Path


class LineBreakRefused(ValueError):
    """A value contained a newline or a carriage return. Its own type because the console
    turns it into a 400 and the CLI lets it surface — see `merge`."""


def _unquote(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        return value[1:-1]
    return value


def parse(text: str) -> dict[str, str]:
    """KEY=value lines. Comments, blanks and malformed lines are skipped;
    `export KEY=value` and quoted values are accepted."""
    out: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if key.startswith("export "):
            key = key[len("export ") :].strip()
        if key:
            out[key] = _unquote(value)
    return out


def merge(path: Path, values: dict[str, str]) -> None:
    """Persist KEY=value pairs, replacing existing lines and appending new ones. Comments
    and unrelated lines are left untouched.

    A newline inside a value is refused here rather than upstream, because upstream is three
    different places: the settings page, the providers panel, and the .env a restore reads
    out of an archive someone else may have built.

    It mattered. Values were written verbatim and joined with "\\n", so one accepted write
    could append lines of its own — and the line worth appending was `CORP_UI_ALLOWED_HOSTS`,
    which SECURITY.md promises cannot be set through the API and which a test asserts is not
    in ALLOWED_VARS. The name was not; the value was. Planting a host there turns off the
    DNS-rebinding defence, and the console stops being localhost-only.

    That is why this function is the single writer, and why `tests/test_security_review.py`
    asserts it: a check in any one caller would have left the other two open.
    """
    bad = sorted(k for k, v in values.items() if "\n" in str(v) or "\r" in str(v))
    if bad:
        raise LineBreakRefused(f"a line break is not allowed in: {', '.join(bad)}")
    lines = path.read_text(encoding="utf-8").splitlines() if path.is_file() else []
    seen = set()
    for i, line in enumerate(lines):
        key = line.split("=", 1)[0].strip()
        if "=" in line and not line.lstrip().startswith("#") and key in values:
            lines[i] = f"{key}={values[key]}"
            seen.add(key)
    lines.extend(f"{k}={v}" for k, v in values.items() if k not in seen)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def merge_into(path: Path, values: dict[str, str]) -> None:
    """`merge`, but creating the file and its directory first.

    Two callers open-coded these four lines — the restore and the secrets CLI — because a
    .env that does not exist yet is the ordinary case on a fresh machine, not an error. The
    console does not need them: it writes to a path it already resolved at startup.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.is_file():
        path.write_text("", encoding="utf-8")
    merge(path, values)
