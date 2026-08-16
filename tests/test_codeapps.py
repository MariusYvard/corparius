"""Programs a company writes, runs, and puts on its own page.

The coder role had no hands. `generate_code` asked a model to "describe a small feature in one
sentence" and returned the sentence; `publish_production_code` returned the literal string
`"Merged PR #42 to production (mock)"` — the same number for every company on every day, behind a
human approval gate, for a merge that never happened. There was no folder for source, no language
and nothing that runs, while a real task drawn from a real document was being queued to that role on
the owner's own install.

Three pieces, split by the layer test rather than by taste:

  * `codeapps` (rank 4) says **what an app is**: a folder, a manifest, a port, what it may see of
    the machine. Pure — it was written with `socket` and `time.sleep` in it and the domain purity
    rule refused it, which was correct.
  * `providers/apprunner` (rank 3) **supervises a process**: start, poll a port, stop, sweep. It
    knows nothing about companies, which is what lets these tests drive it with a two-line script.
  * `write_app_code` writes the program **and starts it**, so its answer is "this runs" rather than
    "code written" — which would have been the mock with more steps.

The bound worth stating is the one that is missing. Memory and disk are not capped: `resource` does
it on POSIX and Windows needs a Job Object, and a limit that exists on one platform is a limit an
operator would believe on three. What there is instead: loopback only, an environment holding `PATH`
and `PORT` and nothing else, a lifetime swept at the top of each run, and everything stopped when the
console exits.
"""

import json
import os
import sys
import textwrap
import time
import types
import urllib.error
import urllib.request

import pytest

from corparius.config import cfg
from corparius.providers import apprunner
from corparius.tools.registry import TOOLS

# A server small enough to read, and a real one: it binds the port it was given and answers JSON.
SERVER = textwrap.dedent(
    """
    import json, os
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from urllib.parse import urlparse, parse_qs

    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            q = (parse_qs(urlparse(self.path).query).get("q") or [""])[0]
            body = json.dumps({"heard": q}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)
        def log_message(self, *a):
            pass

    ThreadingHTTPServer(("127.0.0.1", int(os.environ["PORT"])), H).serve_forever()
    """
).strip()


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("CORP_HOME", str(tmp_path))
    cfg.invalidate()
    yield tmp_path
    apprunner.stop_all()


def _write(source=SERVER, **over):
    """Run the tool the way the executor does, with a structured answer already in hand."""
    data = {
        "name": "listener",
        "language": "python",
        "entry": "main.py",
        "source": source,
        "description": "Repeats what it was asked.",
        **over,
    }
    ctx = types.SimpleNamespace(
        company={"slug": "acme", "name": "Acme"},
        store=None,
        structured=types.SimpleNamespace(data=data),
    )
    return TOOLS["write_app_code"].run(ctx)


# --- three questions, asked one at a time -------------------------------------------
#
# **These exist because a machine nobody here can reach kept saying no.** Every macOS job in CI
# failed on the tests below with "nothing answered on 8771: it was still running after 20s, it wrote
# nothing at all", which is three different faults wearing one sentence: the child never really
# started, or it started and its output does not reach the log, or it started and bound and nothing
# on this machine can connect to loopback. The whole-stack test cannot tell them apart, and neither
# could I from here — so the stack is asked one question at a time, in order, and whichever of these
# three fails names the layer.


def test_a_child_started_this_way_writes_to_its_log(home):
    """Question one: does `proc.start` produce a running program whose output lands in the file we
    later read back? Everything else assumes it."""
    from corparius.kernel import proc

    folder = home / "probe"
    folder.mkdir()
    (folder / "say.py").write_text("print('hello from the child')\n", encoding="utf-8")
    log = folder / "out.log"
    started = proc.start(
        [sys.executable, "say.py"], cwd=str(folder), log=str(log), env=dict(os.environ)
    )
    for _ in range(100):
        if log.read_text(encoding="utf-8", errors="replace").strip():
            break
        time.sleep(0.1)
    started.stop()
    assert "hello from the child" in log.read_text(encoding="utf-8", errors="replace")


def test_a_child_started_this_way_can_bind_a_port_and_be_reached(home):
    """Question two: the socket, on its own. A program that prints "bound" and then holds the port,
    so the log and `listening()` are two independent answers about the same process — and the pair is
    what separates "it never bound" from "it bound and nothing here can connect"."""
    from corparius.kernel import proc
    from corparius.providers import apprunner

    port = 8977
    folder = home / "probe"
    folder.mkdir()
    (folder / "hold.py").write_text(
        "import os, socket\n"
        "s = socket.socket()\n"
        "s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)\n"
        "s.bind(('127.0.0.1', int(os.environ['PORT'])))\n"
        "s.listen(5)\n"
        "print('bound', flush=True)\n"
        "s.accept()\n",
        encoding="utf-8",
    )
    log = folder / "out.log"
    env = {**os.environ, "PORT": str(port), "PYTHONUNBUFFERED": "1"}
    started = proc.start([sys.executable, "hold.py"], cwd=str(folder), log=str(log), env=env)
    reached = apprunner.wait_until_up(port, seconds=15, alive=started.alive)
    said = log.read_text(encoding="utf-8", errors="replace")
    code = started.returncode()
    started.stop()

    assert "bound" in said, f"the child never bound; it said {said!r} and exited with {code}"
    assert reached, f"the child bound {port} and nothing on this machine could connect: {said!r}"


# --- the whole point --------------------------------------------------------------


def test_the_agent_writes_a_program_and_it_runs(home):
    """The claim the old tool could not make. Source on disk, a manifest beside it, a process
    listening, and a real request answered — which is why the tool starts what it wrote instead of
    reporting that it wrote something."""
    from corparius import codeapps

    result = _write()
    assert result.ok is True, result.output

    folder = home / "companies" / "acme" / "code" / "listener"
    assert (folder / "main.py").read_text(encoding="utf-8") == SERVER
    assert (folder / "app.yaml").is_file()

    state = codeapps.status("acme", "listener")
    assert state["running"] and state["answering"], state
    said = urllib.request.urlopen(state["url"] + "/?q=bonjour", timeout=5).read()
    assert json.loads(said) == {"heard": "bonjour"}


def test_a_program_that_does_not_run_is_reported_with_what_it_said(home):
    """The failure that matters most, because it is the one a model will produce. "It did not start"
    is unactionable; the last of the traceback is the whole diagnosis."""
    result = _write(source="import this_module_does_not_exist\n")
    assert result.ok is False
    assert "does not run" in result.output
    assert "ModuleNotFoundError" in result.output or "No module named" in result.output


def test_writing_it_twice_replaces_it_rather_than_fighting_for_the_port(home):
    """The second run on the same app is the normal case — a company improves its own program. The
    old process still holds the port, and starting beside it would make a correct program look
    broken."""
    assert _write().ok is True
    again = _write(source=SERVER.replace('{"heard": q}', '{"heard": q, "v": 2}'))
    assert again.ok is True, again.output

    from corparius import codeapps

    url = codeapps.status("acme", "listener")["url"]
    assert json.loads(urllib.request.urlopen(url + "/?q=x", timeout=5).read())["v"] == 2


def test_a_language_this_cannot_run_is_refused_before_anything_is_written(home):
    result = _write(language="brainfuck")
    assert result.ok is False and "brainfuck" in result.output
    assert not (home / "companies" / "acme" / "code").exists()


def test_the_entry_is_a_file_name_and_never_a_path(home):
    """The value comes out of a model and is used to open a file for writing. `Path(...).name` is
    the whole guard, and it is asserted rather than trusted."""
    _write(entry="../../../escaped.py")
    folder = home / "companies" / "acme" / "code" / "listener"
    assert (folder / "escaped.py").is_file()
    assert not (home / "escaped.py").exists()


# --- what the program may see of the machine ---------------------------------------


def test_the_child_sees_no_credential_of_any_kind(home, monkeypatch):
    """The promise, stated as what it is: **no credentials**, not a list of four variables.

    It was that list first — `PATH`, `PORT`, `PYTHONUNBUFFERED`, `SYSTEMROOT` — and it worked on
    Windows, passed locally and failed every macOS job in CI, with a child that started, wrote
    nothing to its log and never bound its port. Which four variables an interpreter needs is not a
    thing to guess three times.
    """
    from corparius import codeapps

    monkeypatch.setenv("GROQ_API_KEY", "gsk-secret")
    monkeypatch.setenv("CORP_UI_TOKEN", "a-token")
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk-live-secret")
    monkeypatch.setenv("SOME_PASSWORD", "hunter2")
    monkeypatch.setenv("HARMLESS_SETTING", "kept")
    app = codeapps.CodeApp(name="x", language="python", entry="main.py", port=8799)
    env = codeapps.child_env(app)

    assert env["PORT"] == "8799"
    assert env.get("HARMLESS_SETTING") == "kept", "the machine's own environment was thrown away"
    for leaked in ("GROQ_API_KEY", "CORP_UI_TOKEN", "STRIPE_SECRET_KEY", "SOME_PASSWORD"):
        assert leaked not in env, leaked
    assert "gsk-secret" not in " ".join(env.values())


def test_a_program_can_read_its_port_from_the_environment(home):
    """The one thing the contract promises, proved by a program that would not bind without it."""
    assert _write().ok is True
    from corparius import codeapps

    assert codeapps.status("acme", "listener")["answering"] is True


# --- the supervisor, which knows nothing about companies ---------------------------


def test_the_runner_takes_host_arguments_and_no_domain_object(home, tmp_path):
    """The inversion the layer test forced, asserted so it is not undone by convenience. A rank-3
    supervisor importing rank 4 was the first draft; this signature is why the second one is a
    module a test can drive directly."""
    import sys

    script = tmp_path / "tiny.py"
    script.write_text(SERVER, encoding="utf-8")
    out = apprunner.start(
        "t/tiny",
        [sys.executable, "tiny.py"],
        cwd=str(tmp_path),
        log_file=str(tmp_path / "tiny.log"),
        port=8801,
        # A real environment, not an empty one. Windows loads its socket provider out of
        # `SystemRoot`, and a child without it dies on `bind` with `WinError 10106` — which is
        # exactly what the first version of this test produced, and why `codeapps.child_env` carries
        # that one variable beside `PATH` and `PORT`.
        env=dict(os.environ, PORT="8801"),
    )
    assert out["ok"] is True, out
    assert apprunner.running("t/tiny") and apprunner.pid("t/tiny") > 0
    assert apprunner.stop("t/tiny")["stopped"] is True
    assert apprunner.running("t/tiny") is False


def test_a_port_somebody_else_holds_is_said_rather_than_fought_over(home):
    """Starting a process that will exit on bind leaves an operator with a log they have to go and
    find. The refusal names the port and says corparius did not start whatever has it."""
    assert _write().ok is True
    from corparius import codeapps

    app = codeapps.get("acme", "listener")
    out = apprunner.start("other/thing", ["x"], cwd=".", log_file="x.log", port=app.port, env={})
    assert out["ok"] is False and "already in use" in out["error"]


def test_a_lifetime_is_what_bounds_a_program_nobody_is_watching(home):
    """Memory cannot be capped the same way on all three platforms, so a leak is answered by a
    clock. `sweep` runs at the top of every run, which is when somebody is there to read the log."""
    assert _write().ok is True
    assert apprunner.sweep(max_lifetime=10_000) == []
    stopped = apprunner.sweep(max_lifetime=0)
    assert stopped == ["acme/listener"]
    assert apprunner.running("acme/listener") is False


def test_everything_stops_when_the_console_does(home):
    """A corparius that exits leaving programs behind is one an operator has to hunt for in a task
    manager, holding the port the next launch needs."""
    assert _write().ok is True
    assert apprunner.stop_all() == 1
    assert apprunner.running("acme/listener") is False


# --- and onto the page --------------------------------------------------------------


def test_a_program_the_company_lists_appears_on_its_page(home):
    """`site.programs`, and the address is the program's own. A section that named it without saying
    where to reach it would be a heading over nothing.

    **`programs` and not `apps`**, because this company already had a thing called an app: a YAML
    prompt under `apps/` that `site.faq_app` runs at build time. An operator who wrote `site.apps`
    meaning that one was told "this company has no such app" while the file sat right there.
    """
    from corparius import codeapps
    from corparius.sitegen.build import build_site

    assert _write().ok is True
    app = codeapps.get("acme", "listener")
    company = {
        "slug": "acme",
        "name": "Acme",
        "offer": {"product": "A thing", "price_eur": 9},
        "site": {"programs": ["listener"]},
    }
    page = home / "out" / "index.html"
    build_site(company, str(home / "out"))
    html = page.read_text(encoding="utf-8")

    assert 'id="programs"' in html and "listener" in html
    assert app.url in html, "the page names the app and not where to reach it"
    assert "Repeats what it was asked." in html


def test_a_page_with_no_apps_listed_stays_a_static_file(home):
    """The property the generator has defended from the start: nothing to reach, nothing left
    running. This section is the one exception and it is opt-in, so a company that did not ask keeps
    exactly the page it had."""
    from corparius.sitegen.build import build_site

    assert _write().ok is True  # the app exists, and is deliberately not listed
    build_site({"slug": "acme", "name": "Acme", "offer": {"product": "A thing"}}, str(home / "out"))
    html = (home / "out" / "index.html").read_text(encoding="utf-8")

    assert 'id="programs"' not in html
    # The app widget's script, not any script: the page has always carried a JSON-LD block, which is
    # structured data rather than behaviour and reaches nothing.
    # The *markup*, not the word. The stylesheet is one static blob carrying rules for every
    # section a page might have — `.voices`, `.proof`, `.faq` and now `.program-out` — and the
    # first version of this assertion looked for the bare class name, so it started failing the
    # moment those cards got a design. What must be absent is the form, not its rules.
    assert 'class="program-out"' not in html, "a page nobody asked to be interactive grew a form"
    assert "fetch(" not in html, "a page nobody asked to be interactive grew a request"


def test_an_app_that_is_listed_and_does_not_exist_is_left_out(home):
    """`company.yaml` is edited by hand and an app can be deleted. A form pointing at a program that
    is not there is worse than no form: it fails when a visitor uses it rather than when the page is
    built."""
    from corparius.sitegen.build import build_site

    build_site(
        {
            "slug": "acme",
            "name": "Acme",
            "offer": {"product": "x"},
            "site": {"programs": ["ghost"]},
        },
        str(home / "out"),
    )
    assert 'id="programs"' not in (home / "out" / "index.html").read_text(encoding="utf-8")


# --- and the tools that still do nothing say so --------------------------------------


def test_no_tool_advertises_work_it_does_not_do():
    """The list this file used to keep is **empty**, and the assertion inverts rather than being
    deleted.

    There were three. Each returned a sentence describing work it had not done — `generate_code`
    asked a model for one sentence about a feature and returned the sentence, `publish_production_code`
    said "Production code published" and touched nothing, `produce_mockup` said "landing hero and one
    ad variant (mock)" every time. The first repair was honest labelling: their descriptions began
    with "Not built", so an operator reading a log could tell them apart from the tools that act.
    All three do the work now, so the label has nowhere left to sit.

    Kept as an assertion over the whole registry because that is the direction that can fail again:
    a new tool describing itself as a placeholder is a tool the roster will hand real turns to.
    """
    placeholders = sorted(n for n, t in TOOLS.items() if "not built" in t.description.lower())
    assert placeholders == [], placeholders
    for repaired in ("generate_code", "publish_production_code", "produce_mockup"):
        assert repaired in TOOLS, repaired


def test_the_one_with_hands_is_on_the_coder_s_playbook():
    from corparius.kernel.records import AgentRole
    from corparius.roster import ROSTER

    assert ROSTER[AgentRole.CODER].playbook[0] == "write_app_code"


# --- and nothing accumulates without end ---------------------------------------------


def test_a_company_cannot_collect_programs_forever(home):
    """The failure this ceiling exists for is specific rather than theoretical.

    A model asked every day to write an app has no memory of the name it chose yesterday, so it
    invents `demo`, then `demo-v2`, then `retour-vocal` — a folder, a process and a port each,
    against fifty ports and no limit. The seventh is refused, and the refusal names what is already
    there so the next round has somewhere to go.
    """
    from corparius import codeapps

    for i in range(codeapps.MAX_APPS):
        assert _write(name=f"app-{i}").ok is True, f"app-{i} was refused early"

    seventh = _write(name="one-too-many")
    assert seventh.ok is False
    assert "limit" in seventh.output and "app-0" in seventh.output
    assert len(codeapps.load("acme")) == codeapps.MAX_APPS


def test_improving_an_existing_program_is_never_what_hits_the_ceiling(home):
    """A company making its own program better is the normal case, and a ceiling that blocked it
    would push the model into inventing a name to get around it — which is the thing being
    prevented."""
    from corparius import codeapps

    for i in range(codeapps.MAX_APPS):
        assert _write(name=f"app-{i}").ok is True
    again = _write(name="app-3", source=SERVER.replace('{"heard": q}', '{"heard": q, "v": 2}'))
    assert again.ok is True, again.output
    assert len(codeapps.load("acme")) == codeapps.MAX_APPS


def test_a_log_that_grows_past_its_limit_keeps_the_end(home):
    """A program that logs a line per request writes without limit otherwise. Halved rather than
    emptied: a program that fails at start writes its traceback and nothing else, and truncating on
    the way past would throw away the only thing anybody reads."""
    from corparius import codeapps

    logfile = home / "big.log"
    logfile.write_bytes(b"old line\n" * 200_000 + b"THE NEWEST LINE\n")
    assert logfile.stat().st_size > codeapps.MAX_LOG_BYTES

    assert codeapps.trim_log(logfile) is True
    kept = logfile.read_text(encoding="utf-8")
    assert "THE NEWEST LINE" in kept
    assert "earlier lines dropped" in kept
    assert logfile.stat().st_size <= codeapps.MAX_LOG_BYTES


def test_a_log_under_the_limit_is_left_exactly_as_it_is(home):
    from corparius import codeapps

    logfile = home / "small.log"
    logfile.write_text("a short log\n", encoding="utf-8")
    assert codeapps.trim_log(logfile) is False
    assert logfile.read_text(encoding="utf-8") == "a short log\n"


def test_the_log_is_trimmed_before_a_launch_and_not_while_it_is_held(home):
    """On Windows a file a running child holds open is not writable, so the moment to trim is the
    one before the process exists. Asserted through a real launch."""
    from corparius import codeapps

    assert _write().ok is True
    codeapps.halt("acme", "listener")
    logfile = home / "companies" / "acme" / "code" / "listener" / "app.log"
    logfile.write_bytes(b"noise\n" * 200_000)

    assert codeapps.launch("acme", "listener")["ok"] is True
    assert logfile.stat().st_size <= codeapps.MAX_LOG_BYTES


def test_the_running_set_does_not_keep_what_has_died(home):
    """`_running` is a dict in memory and a stale entry would report a process that is gone.
    `sweep` forgets those, which is what makes the count it reports believable."""
    assert _write().ok is True
    apprunner.stop("acme/listener")
    apprunner.sweep()
    assert "acme/listener" not in apprunner._running
    assert apprunner.stop_all() == 0


def test_an_app_keeps_its_address_across_restarts(home):
    """The property the sales page depends on: its markup holds the address, so a port that moved on
    restart would mean rebuilding the page on restart.

    Asserted in a **subprocess**, because that is the only place the bug could be seen. Python
    randomises `hash()` per interpreter, so the first version of this function was perfectly stable
    within one process and gave a different port to every launch — which is exactly the sort of
    thing a same-process assertion reports as working.
    """
    import subprocess
    import sys

    probe = "from corparius import codeapps; print(codeapps._port_for('vigil', 'demo'))"
    ports = {
        subprocess.run(
            [sys.executable, "-c", probe], capture_output=True, text=True, check=True
        ).stdout.strip()
        for _ in range(3)
    }
    assert len(ports) == 1, f"the port moved between interpreters: {ports}"


def test_two_programs_never_share_one_port(home):
    """A birthday problem over fifty slots: about one company in four with six apps would have two
    of them derive the same number, and the second would fail to bind with no explanation."""
    from corparius import codeapps

    for i in range(codeapps.MAX_APPS):
        assert _write(name=f"app-{i}").ok is True

    ports = [app.port for app in codeapps.load("acme")]
    assert len(set(ports)) == len(ports), f"two apps share a port: {sorted(ports)}"
    assert all(codeapps.PORT_FLOOR <= p < codeapps.PORT_CEILING for p in ports)


# --- the two tools that used to be strings ------------------------------------------


def test_a_broken_program_is_repaired_from_its_own_log(home):
    """The loop that was missing entirely. `write_app_code` writes something new; this reads the
    traceback of a program that stopped answering and writes the corrected file. Two tools because
    they are two jobs — a single one asked to do both gets a prompt describing neither.

    What it replaced: `generate_code` asked a model to describe a feature in one sentence and
    returned that sentence.
    """
    import types

    from corparius import codeapps

    assert _write(source="import a_module_that_is_not_installed\n").ok is False

    ctx = types.SimpleNamespace(company={"slug": "acme", "name": "Acme"}, store=None)
    asked = TOOLS["generate_code"].draft_prompt(ctx)
    assert "listener" in asked, "the prompt does not name the program that is down"
    assert "No module named" in asked or "ModuleNotFoundError" in asked, (
        "the prompt does not carry the traceback, so a model would rewrite from memory"
    )

    fixed = TOOLS["generate_code"].run(
        types.SimpleNamespace(
            company={"slug": "acme", "name": "Acme"},
            store=None,
            structured=types.SimpleNamespace(
                data={"name": "listener", "source": SERVER, "why": "the import did not exist"}
            ),
        )
    )
    assert fixed.ok is True, fixed.output
    assert codeapps.status("acme", "listener")["answering"] is True


def test_the_repair_tool_stands_down_when_everything_answers(home):
    """Most days nothing is broken. A tool that rewrote a working program to have something to do is
    the shape `stop_useless_work` exists to catch."""
    import types

    assert _write().ok is True
    ctx = types.SimpleNamespace(company={"slug": "acme"}, store=None)
    assert "nothing to repair" in TOOLS["generate_code"].behaviour.skip_when(ctx)


def test_a_repair_that_still_does_not_run_is_a_failure(home):
    """Same contract as writing one: the claim is that the program runs, so a rewrite that does not
    start is reported as one rather than as a fix."""
    import types

    assert _write(source="import nope_not_here\n").ok is False
    out = TOOLS["generate_code"].run(
        types.SimpleNamespace(
            company={"slug": "acme"},
            store=None,
            structured=types.SimpleNamespace(
                data={"name": "listener", "source": "import still_not_here\n"}
            ),
        )
    )
    assert out.ok is False and "still does not run" in out.output


def test_publishing_puts_the_source_on_the_remote(home, tmp_path):
    """What this used to be: `return "Merged PR #42 to production (mock)"` — a fixed string, the same
    number for every company on every day, behind a human approval gate for a merge that never
    happened. It commits the company's own `code/` and pushes it.
    """
    import subprocess
    import types

    from corparius.providers import companyrepo

    if not companyrepo.git_available():
        pytest.skip("git is not on PATH")

    assert _write().ok is True
    bare = tmp_path / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(bare)], check=True)
    companyrepo._git(["remote", "add", "origin", str(bare)], companyrepo.ensure_repo("acme"))

    ctx = types.SimpleNamespace(company={"slug": "acme"}, store=None)
    out = TOOLS["publish_production_code"].run(ctx)
    assert out.ok is True, out.output

    listed = subprocess.run(
        ["git", "--git-dir", str(bare), "ls-tree", "-r", "--name-only", "main"],
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    assert "code/listener/main.py" in listed, listed
    assert "code/listener/app.log" not in listed, "the program's output was versioned too"


def test_a_second_publish_says_there_was_nothing_new(home, tmp_path):
    """And it is a *check* rather than an assumption. The first version called `sync`, which returns
    early on a clean tree, and reported "nothing had changed since the last publish" about a company
    whose code had **never** been pushed — the remote held no `code/` at all. Unknown now means
    everything is unpushed, not nothing."""
    import subprocess
    import types

    from corparius.providers import companyrepo

    if not companyrepo.git_available():
        pytest.skip("git is not on PATH")

    assert _write().ok is True
    bare = tmp_path / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(bare)], check=True)
    companyrepo._git(["remote", "add", "origin", str(bare)], companyrepo.ensure_repo("acme"))

    ctx = types.SimpleNamespace(company={"slug": "acme"}, store=None)
    first = TOOLS["publish_production_code"].run(ctx)
    second = TOOLS["publish_production_code"].run(ctx)
    assert first.ok and second.ok
    assert "pushed" in first.output and "already" in second.output


def test_publishing_without_a_remote_is_refused_with_the_fact(home):
    """No terminal command in the sentence: creating a company repository is not something the
    console can do yet, and pointing at one would be the product handing its own work back."""
    import types

    assert _write().ok is True
    out = TOOLS["publish_production_code"].run(
        types.SimpleNamespace(company={"slug": "acme"}, store=None)
    )
    assert out.ok is False and "not versioned" in out.output
    assert "corparius " not in out.output, "the refusal names a command to run"
