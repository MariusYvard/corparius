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
