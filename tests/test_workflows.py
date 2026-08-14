"""The Python inside the CI workflows, checked from here.

Written because one of those snippets had been broken since stage 1 and nothing said so.
`wheel-smoke` ran `from corparius import paths`, and stage 1 moved that module to
`corparius/kernel/paths.py` — so the step that proves an installed wheel can find its own shipped
resources was failing on its first line, and the only place it could be noticed was a CI log
nobody reads when the rest is green.

That is the shape this project keeps refusing: a guard that does not run. The workflow files are
the one part of the repository the test suite never executes, so the imports inside them are
checked here instead — cheaply, by resolving each one.

`ast.parse` would not have caught it: the snippet is syntactically fine. What is wrong is a name,
and only an import can tell.
"""

import ast
import importlib
import pathlib
import re

import pytest

WORKFLOWS = sorted(pathlib.Path(".github/workflows").glob("*.yml"))


def _python_blocks(text: str) -> list[str]:
    """The inline heredoc Python in a workflow: `python - <<'PY' ... PY`.

    Dedented to the heredoc's own indentation, because YAML indents the whole block and Python
    would otherwise refuse to parse what CI runs perfectly well.
    """
    blocks = []
    for match in re.finditer(r"<<'(\w+)'\n(.*?)\n\s*\1\b", text, re.S):
        body = match.group(2)
        lines = body.splitlines()
        pad = min((len(line) - len(line.lstrip()) for line in lines if line.strip()), default=0)
        blocks.append("\n".join(line[pad:] for line in lines))
    return blocks


def test_there_are_workflows_to_check():
    """The guard on the guard, and it earns its place here: a glob that matched nothing would make
    this whole file a green tick over an unchecked directory."""
    assert WORKFLOWS, "no workflow files found"
    assert any("ci.yml" == p.name for p in WORKFLOWS)


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda p: p.name)
def test_the_inline_python_parses(path):
    for i, block in enumerate(_python_blocks(path.read_text(encoding="utf-8"))):
        try:
            ast.parse(block)
        except SyntaxError as exc:  # pragma: no cover - the failure is the message
            pytest.fail(f"{path.name} block {i} does not parse: {exc}\n{block[:400]}")


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda p: p.name)
def test_every_module_a_workflow_imports_still_exists(path):
    """The one that would have caught it.

    Resolves each `from corparius... import name` the workflows contain: the module must import and
    the names must be there. Cheap, and it is the difference between finding a moved module here and
    finding it in a release job.
    """
    text = path.read_text(encoding="utf-8")
    found = re.findall(r"^\s*from (corparius[\w.]*) import ([^\n#]+)", text, re.M)
    assert found or path.name != "ci.yml", "ci.yml no longer imports the package at all"
    for module_name, names in found:
        module = importlib.import_module(module_name)
        for name in (n.strip() for n in names.split(",")):
            attribute = name.split(" as ")[0].strip()
            assert hasattr(module, attribute), (
                f"{path.name} imports {attribute!r} from {module_name}, which does not have it. "
                "A workflow is the one place a broken import hides behind a green suite."
            )


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda p: p.name)
def test_every_paths_helper_a_workflow_calls_still_exists(path):
    """The same check one level down. The wheel smoke asserts on `paths.page_file()`,
    `paths.console_built()` and friends; a renamed helper would fail there and only there."""
    from corparius.kernel import paths

    called = set(re.findall(r"\bpaths\.(\w+)\(", path.read_text(encoding="utf-8")))
    missing = sorted(name for name in called if not hasattr(paths, name))
    assert not missing, f"{path.name} calls paths.{missing} which no longer exist"


def _steps(job: str) -> list[str]:
    """Every `run:` script of a job, in order.

    Parsed with YAML rather than sliced out of the text. The first version split on the job name and
    then on the next two-space indent, which cut at the job's own first key and produced an empty
    string — a test that passed for one job and failed for the other, for a reason that had nothing
    to do with what it was checking. PyYAML is one of this project's two runtime dependencies, so
    reading the file properly costs nothing.
    """
    import yaml

    ci = yaml.safe_load(pathlib.Path(".github/workflows/ci.yml").read_text(encoding="utf-8"))
    return [str(step.get("run", "")) for step in ci["jobs"][job]["steps"]]


def test_the_console_is_built_before_anything_packages_it():
    """Order, and it only matters in one direction: the wheel and the frozen spec pick up
    `corparius/api/static/` if it is there, so a packaging job that builds the artefact before
    running `npm run build` ships a product with no `/app/` and no error to show for it."""
    for job, packager in (("package-smoke", "pyinstaller"), ("wheel-smoke", "python -m build")):
        runs = _steps(job)
        built = next((i for i, r in enumerate(runs) if "npm run build" in r), None)
        packaged = next((i for i, r in enumerate(runs) if packager in r), None)
        assert built is not None, f"{job} does not build the console"
        assert packaged is not None, f"{job} does not run {packager}"
        assert built < packaged, (
            f"{job} packages at step {packaged} and builds the console at {built}, so /app/ "
            "would be missing from the artefact"
        )


def test_the_wheel_smoke_asserts_the_console_rides_inside_the_wheel():
    """The installed mode is the one where a mis-declared resource is hardest to notice from a
    checkout, because the checkout has the file either way."""
    smoke = chr(10).join(_steps("wheel-smoke"))
    assert "paths.console_built()" in smoke
    assert "/app/" in smoke, "and it has to be served, not merely present on disk"


def test_the_frozen_smoke_asserts_the_console_is_in_the_bundle():
    """`sys._MEIPASS` is only exercised by a frozen build, so this is the single place that
    resolution mode runs at all."""
    smoke = chr(10).join(_steps("package-smoke"))
    assert "/app/" in smoke
    assert "console.js" in smoke, "the shell alone would not prove the assets came along"


# --- the shell, and the class of defect that cost three red pushes ----------------


def _code(script: str) -> str:
    """A `run:` block with its comment lines removed.

    **Third time in one session that a rule matched the prose explaining the rule** — a comment
    quoting `{#key shown.id}`, a comment quoting a CSS declaration, and now the comment above
    `contains` that quotes `curl | grep -q` in order to forbid it. A rule that cannot tell code from
    writing about code punishes the writing, and the writing is where the measurements live.

    Whole-line comments only: a trailing `#` may be inside a string or a URL fragment, and dropping
    the rest of the line would make this a parser it has no need to be.
    """
    kept = [line for line in script.splitlines() if not line.lstrip().startswith("#")]
    return "\n".join(kept)


def _scripts() -> dict[str, str]:
    """Every `run:` block in every workflow, keyed by file, job and step name.

    Wider than `_steps`, which reads one job of `ci.yml`: the two rules below apply to release.yml
    too, and the release job is exactly where a defect is most expensive — it runs on a tag, after
    six builds, in front of whoever is downloading.
    """
    import yaml

    found: dict[str, str] = {}
    for path in WORKFLOWS:
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        for job_name, job in (doc.get("jobs") or {}).items():
            for i, step in enumerate(job.get("steps") or []):
                if "run" in step:
                    found[f"{path.name}::{job_name}::{step.get('name', f'step {i}')}"] = step["run"]
    return found


def test_there_are_scripts_to_check():
    """The guard on the guard, again, and for the same reason as the one at the top of this file."""
    scripts = _scripts()
    assert len(scripts) >= 15, f"only {len(scripts)} run blocks found — the walk is wrong"


def test_a_helper_is_defined_in_every_block_that_calls_it():
    """**Measured, at the cost of a build.** `contains` was written once and called from four `run:`
    blocks across two workflows — and each block is its own shell, so a function defined in one is
    not defined in the next. The push failed with `contains: command not found`, exit 127, after a
    PyInstaller build had already run.

    A `run:` block is a script, and a script calling a function it does not define is broken in a way
    that reading the diff does not catch, because the definition *is* right there — in another step.
    """
    for key, script in _scripts().items():
        code = _code(script)
        called = set(re.findall(r"^\s*([a-z_][a-z0-9_]*) [\"']", code, re.M))
        defined = set(re.findall(r"^\s*([a-z_][a-z0-9_]*)\(\)\s*\{", code, re.M))
        # Only the names this file knows are helpers. Every other bare word is a real command.
        for helper in ("contains", "checked"):
            assert not (helper in called and helper not in defined), (
                f"{key} calls `{helper}` and no step-local definition exists"
            )


def test_nothing_is_piped_into_a_quiet_grep():
    """The defect that cost three red pushes. `grep -q` exits at the **first match** and closes the
    pipe, so whatever is still writing takes EPIPE — and under `set -o pipefail` that fails the job.

    It is timing-dependent on how much is still in flight, which is why these passed for weeks and
    then failed on a run where nothing about them had changed: `curl: (23) Failure writing output to
    destination`. **Fixing the producer does not fix it** — capturing each body first moved the race
    from `curl` to `echo`, which then failed on `/legacy`, the largest body in the step, with
    `echo: write error: Broken pipe`.

    So the rule is about the consumer: nothing is piped into `grep -q` at all. A `case` over a
    variable already in memory has no pipe to break, and it can say what was missing, which `grep -q`
    never could.

    `grep -o` is deliberately allowed: it prints every match and reads to EOF, so it never closes a
    pipe early and cannot produce this failure.
    """
    for key, script in _scripts().items():
        for line in _code(script).splitlines():
            assert not ("|" in line and re.search(r"\|\s*grep\s+-\w*q", line)), (
                f"{key}: `{line.strip()}` — grep -q closes the pipe at the first match and the "
                "writer takes EPIPE. Capture the body and use `contains`."
            )
