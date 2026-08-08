"""`app/` holds use cases, and the two rules that keep it from being a renamed handler folder.

The plan names the failure mode: moving a route handler into a different directory and calling
it a layer. Two properties tell the difference, and both are checkable.

**No `Ctx` parameter.** `Ctx` carries an HTTP request — body, headers, query string. A service
taking one has not been lifted out of the transport, it has been relabelled.

**No transport error.** A service that raises the console's 400 can only ever be called by the
console. It raises what the failure *is*, and the route translates. The pattern already exists
one rank down: `kernel/dotenv.merge` raises `LineBreakRefused`, and `adapters.merge_env_file`
turns that into a status code.

The measured reason the folder exists: eleven things the console could do and the command line
could not, because the logic lived in the handler. `corparius set` is the first one closed.
"""

import ast
from pathlib import Path

import pytest

APP = Path("corparius/app")
SOURCES = sorted(APP.rglob("*.py"))

# Names that mean "an HTTP request reached this far".
TRANSPORT_TYPES = {"Ctx", "BaseHTTPRequestHandler", "Handler"}
TRANSPORT_ERRORS = {"_RequestRefused", "RequestRefused"}


def _functions() -> list[tuple[str, ast.FunctionDef | ast.AsyncFunctionDef]]:
    out = []
    for path in SOURCES:
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                out.append((path.as_posix(), node))
    return out


def test_there_is_an_app_layer_to_check():
    """The guard on the guard: an empty glob would make everything below vacuous, which is the
    exact failure this file exists to catch one level up."""
    assert SOURCES, "corparius/app/ has no modules; the glob stopped matching"
    assert _functions(), "no functions found in corparius/app/"


def test_no_service_takes_a_request():
    """The load-bearing rule. A parameter annotated `Ctx` is a handler wearing a new folder."""
    offenders = []
    for where, fn in _functions():
        for arg in [*fn.args.args, *fn.args.kwonlyargs]:
            if arg.annotation is None:
                continue
            annotated = ast.unparse(arg.annotation)
            if any(t in annotated for t in TRANSPORT_TYPES):
                offenders.append(f"{where}::{fn.name}({arg.arg}: {annotated})")
    assert not offenders, (
        "these take an HTTP request, so they are route handlers in a different directory: "
        + ", ".join(offenders)
    )


def test_no_service_names_a_request_parameter_ctx():
    """The same rule, for the unannotated case — most of this codebase's handlers spell it
    `ctx` and annotate nothing, so checking annotations alone would miss every one."""
    offenders = [
        f"{where}::{fn.name}"
        for where, fn in _functions()
        if any(a.arg in ("ctx", "handler", "request") for a in [*fn.args.args, *fn.args.kwonlyargs])
    ]
    assert not offenders, f"these name a request parameter: {offenders}"


def test_no_service_raises_a_transport_error():
    """A service raising a status code can only be called by the thing that speaks status
    codes. It raises the failure; the route decides what that is worth over HTTP."""
    offenders = []
    for where, fn in _functions():
        for node in ast.walk(fn):
            if isinstance(node, ast.Raise) and node.exc is not None:
                raised = ast.unparse(node.exc)
                if any(e in raised for e in TRANSPORT_ERRORS):
                    offenders.append(f"{where}::{fn.name} raises {raised}")
    assert not offenders, f"these raise a transport error: {offenders}"


def test_the_app_layer_imports_no_transport():
    """`api`, `appserver` and `http.server` are rank 6. An app service importing one would
    be an upward import — `tests/test_layers.py` would catch it too, and this says why.

    `webui` is in the list still, and deliberately: the module is gone, so an import of it can
    only be a leftover — but it costs one word to say that a resurrection would not pass."""
    banned = {"api", "webui", "appserver", "http.server", "http"}
    offenders = []
    for path in SOURCES:
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ImportFrom) and node.module:
                head = node.module.lstrip(".").split(".")[0]
                if head in banned:
                    offenders.append(f"{path.as_posix()} imports {node.module}")
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.split(".")[0] in banned:
                        offenders.append(f"{path.as_posix()} imports {alias.name}")
    assert not offenders, offenders


@pytest.mark.parametrize("path", [p.as_posix() for p in SOURCES if p.name != "__init__.py"])
def test_every_service_module_says_what_it_is_for(path):
    """These are the modules two callers share. A module with no docstring is one where the
    next person has to read both callers to find out which behaviour is the contract."""
    tree = ast.parse(Path(path).read_text(encoding="utf-8"))
    assert ast.get_docstring(tree), f"{path} has no module docstring"
