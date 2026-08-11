"""Stage 10, as an acceptance test: a phone-shaped client on v1 and nothing else.

The plan says there is nothing to invent once stage 8 is done — "l'app consomme v1, garde son jeton
d'appareil, et se limite aux approbations, l'inbox, le backlog, lancer/arrêter un tour distant". What
corparius owes is not an iOS project in a Python repository; it is **proof that the v1 surface is
sufficient for exactly that scope**, exercised the way a device would: over the wire, with a paired
credential, against a core it did not start.

So this file is that client. It pairs, reads, decides, and drives a run, and every call goes through
HTTP with `Authorization: Bearer` — no imports of `corparius.app`, no store handle, nothing a phone
could not do. If a request here needs something v1 does not offer, this fails and the surface is
incomplete, which is the only useful definition of "stage 10 is possible".

**Two scopes, not ten.** `read` can look and cannot act, and that is asserted rather than assumed: a
lost phone paired read-only must not be able to start a run or approve a payment.

**What it does not promise.** Running the loop in the background on the device. Neither mobile OS
guarantees it, and the plan refuses to claim an autonomy the OS does not keep — so the client starts a
run *on the core* and watches it, which survives the app being closed because the run was never in the
app. That distinction is the whole reason schema 19 exists, and `test_a_run_survives_the_console_that_started_it`
is its proof; here it is asserted from the client's side.
"""

import json
import shutil
import threading
from http.client import HTTPConnection

import pytest

from corparius.store import clients as clients_store


class Device:
    """A phone, as far as the core can tell: a base URL and a bearer token.

    Deliberately thin and deliberately over HTTP. A helper that reached into `app/` would prove the
    services work, which other tests already do; only a socket proves the *surface* does.
    """

    def __init__(self, port: int, token: str):
        self.port = port
        self.token = token

    def _call(self, method: str, path: str, body=None):
        conn = HTTPConnection("127.0.0.1", self.port, timeout=20)
        conn.request(
            method,
            path,
            json.dumps(body) if body is not None else None,
            {"Content-Type": "application/json", "Authorization": f"Bearer {self.token}"},
        )
        res = conn.getresponse()
        raw = res.read()
        conn.close()
        return res.status, json.loads(raw or b"{}")

    # The five things the plan says a thin client does, and nothing else.
    def summary(self, slug):
        return self._call("GET", f"/api/v1/summary?company={slug}")

    def backlog(self, slug):
        return self._call("GET", f"/api/v1/tasks?company={slug}")

    def jobs(self, slug):
        return self._call("GET", f"/api/v1/jobs?company={slug}")

    def decide(self, approval_id, decision):
        return self._call("POST", "/api/v1/approvals", {"id": approval_id, "decision": decision})

    def answer_inbox(self, item, slug):
        return self._call("POST", "/api/v1/inbox", {"id": item, "answer": "", "company": slug})

    def start_run(self, slug, ticks=2, key=""):
        conn = HTTPConnection("127.0.0.1", self.port, timeout=20)
        headers = {"Content-Type": "application/json", "Authorization": f"Bearer {self.token}"}
        if key:
            headers["Idempotency-Key"] = key
        conn.request("POST", "/api/v1/runs", json.dumps({"company": slug, "ticks": ticks}), headers)
        res = conn.getresponse()
        out = (res.status, json.loads(res.read() or b"{}"))
        conn.close()
        return out

    def stop_run(self, slug):
        return self._call("POST", "/api/v1/runs/stop", {"company": slug})


@pytest.fixture()
def core(tmp_path, monkeypatch):
    """A core with a company, and a device paired to it. Nothing else."""
    from corparius.api.server import build_server
    from corparius.config import cfg
    from corparius.config.settings import Settings

    from .conftest import EXAMPLE_COMPANY

    monkeypatch.setenv("CORP_DATA_PATH", str(tmp_path / "data"))
    monkeypatch.setenv("CORP_LLM_MOCK", "true")
    # A device credential must work whether or not the shared bootstrap token is set. It is set here
    # precisely so a passing test cannot be a test where nothing is checked at all.
    monkeypatch.setenv("CORP_UI_TOKEN", "the-shared-bootstrap-one")
    home = tmp_path / "home"
    shutil.copytree(EXAMPLE_COMPANY, home / "companies" / "example")
    monkeypatch.setenv("CORP_HOME", str(home))
    cfg.set_dotenv_path(tmp_path / ".env")
    cfg.invalidate()
    srv = build_server(Settings(), host="127.0.0.1", port=0, env_file=tmp_path / ".env")
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    port = srv.socket.getsockname()[1]
    store = srv.RequestHandlerClass.state.store()
    yield srv, port, store
    srv.shutdown()
    srv.server_close()


def _pair(store, name="the phone", scope=clients_store.ACT):
    """What `corparius pair` does. The token is returned once and stored as a hash."""
    return store.pair_client(name, scope)["token"]


def _approval(store, ident="ap1", tool="draft_social_post"):
    from corparius.kernel.records import ApprovalRequest

    store.add_approval(
        ApprovalRequest(id=ident, company="example", agent="social", tool=tool, parameters={"x": 1})
    )
    return ident


# --- the credential ---------------------------------------------------------------


def test_a_paired_device_reads_without_the_shared_token(core):
    """The point of schema 20. `CORP_UI_TOKEN` has no name, no scope and no way to withdraw it from one
    device without changing it for all of them; this is what a second client gets instead."""
    _srv, port, store = core
    phone = Device(port, _pair(store))
    status, data = phone.summary("example")
    assert status == 200, data
    assert data["company"] == "example"


def test_an_unpaired_token_is_refused_with_a_code(core):
    """`unauthenticated` as a word, not a sentence — which is what lets a client show a pairing screen
    instead of matching prose that gets reworded."""
    _srv, port, _store = core
    status, data = Device(port, "corp_not-a-real-token").summary("example")
    assert status == 401
    assert data["error"]["code"] == "unauthenticated"


def test_revoking_a_device_locks_it_out_and_leaves_the_others(core):
    """The property the shared token could not have: a lost phone is revoked without logging out the
    laptop."""
    _srv, port, store = core
    lost = _pair(store, "lost phone")
    kept = _pair(store, "laptop")
    row = next(c for c in store.list_clients() if c["name"] == "lost phone")
    assert store.revoke_client(row["id"]) is True
    assert Device(port, lost).summary("example")[0] == 401
    assert Device(port, kept).summary("example")[0] == 200


def test_read_scope_can_look_and_cannot_act(core):
    """Two scopes, not ten — and this is the assertion that makes the second one mean something. A
    phone paired read-only must not be able to approve a payment or start a run."""
    _srv, port, store = core
    _approval(store)
    phone = Device(port, _pair(store, "read-only phone", clients_store.READ))

    assert phone.summary("example")[0] == 200
    assert phone.backlog("example")[0] == 200

    for status, data in (
        phone.decide("ap1", "approved"),
        phone.start_run("example"),
        phone.stop_run("example"),
    ):
        assert status == 403, data
        assert data["error"]["code"] == "forbidden"
    # And nothing happened: a refusal that had already written would be worse than one that lied.
    assert store.get_approval("ap1")["status"] == "pending"


# --- the scope the plan names -----------------------------------------------------


def test_the_phone_sees_what_needs_a_person(core):
    """Approvals and the inbox in one read, which is why they are in `summary` rather than behind two
    routes: they are the two things an operator must not have to make a second request to see."""
    _srv, port, store = core
    _approval(store)
    store.add_inbox("example", "design", "question", "Which price?")
    phone = Device(port, _pair(store))
    _status, data = phone.summary("example")
    assert [a["id"] for a in data["approvals"]] == ["ap1"]
    assert len(data["inbox"]) == 1
    # Enough to decide on, not just a tool name: what it does, why it stopped, what yes and no mean.
    assert data["approvals"][0]["detail"]["does"]
    assert data["approvals"][0]["risk"]


def test_the_phone_decides_and_the_work_moves(core):
    """The whole point of a phone in this product. Deciding has to *finish* — the console once granted
    the standing rule and never released the work parked on the approval, so the board still read
    "Held, waiting on you" and nothing moved until a run ticked."""
    _srv, port, store = core
    _approval(store)
    task = store.add_task("example", "work held by the approval", "social")
    store.park_task(task, "ap1", "approval")
    phone = Device(port, _pair(store))

    status, data = phone.decide("ap1", "approved")
    assert status == 200
    assert data["released"] == 1, "an approval that unblocks nothing has not finished"
    assert store.get_task(task)["status"] != "waiting"


def test_the_phone_answers_the_inbox(core):
    _srv, port, store = core
    item = store.add_inbox("example", "design", "question", "Which price?")
    task = store.add_task("example", "waiting on the answer", "social")
    store.park_task(task, item, "question")
    phone = Device(port, _pair(store))
    status, data = phone.answer_inbox(item, "example")
    assert status == 200 and data["released"] == 1


def test_the_phone_reads_the_backlog(core):
    _srv, port, store = core
    store.add_task("example", "a proposal", "design", status="proposed")
    phone = Device(port, _pair(store))
    _status, data = phone.backlog("example")
    assert [t["title"] for t in data["tasks"]["proposed"]] == ["a proposal"]
    assert "done_total" in data, "a bounded column needs its true count beside it"


# --- driving a run it does not host ----------------------------------------------


def test_the_phone_starts_a_run_on_the_core_and_watches_it(core):
    """**Not** in the app. The run is a `jobs` row on the core, so closing the phone does not stop it
    and reopening it finds it again — which is the honest version of "run my company from my phone",
    and the reason the plan refuses to promise background execution on the device."""
    _srv, port, store = core
    phone = Device(port, _pair(store))
    status, started = phone.start_run("example", ticks=2)
    assert status == 200, started
    assert started["job"], "a client needs the id to follow it"

    _status, seen = phone.jobs("example")
    assert any(j["id"] == started["job"] for j in seen["jobs"])
    # `owner_token` is how the startup sweep decides whether a running job is this process's, and a
    # client has nothing it could do with it.
    assert all("owner_token" not in j for j in seen["jobs"])


def test_a_retry_over_a_bad_connection_does_not_start_two_runs(core):
    """The 4G case the `Idempotency-Key` exists for: a phone that loses the answer asks again with the
    same key and gets **the same job** with `created: false`, rather than a refusal it would have to
    interpret or a second run it did not ask for."""
    _srv, port, store = core
    phone = Device(port, _pair(store))
    status, first = phone.start_run("example", ticks=2, key="phone-abc-123")
    assert status == 200 and first["created"] is True
    status, again = phone.start_run("example", ticks=2, key="phone-abc-123")
    assert status == 200
    assert again["created"] is False
    assert again["job"] == first["job"], "the retry started a second run"


def test_the_phone_stops_a_run_the_console_started(core):
    """`cancel_requested` is a column, not a `threading.Event`, and this is what that buys: the phone
    was not there when the run began and can still stop it."""
    from corparius.app import runs as app_runs

    _srv, port, store = core
    # Started by somebody else entirely — no `threading.Event` anywhere near this phone.
    job = store.start_job(app_runs.KIND, "example", progress="tick 3")["id"]
    phone = Device(port, _pair(store))
    status, data = phone.stop_run("example")
    assert status == 200, data
    assert store.cancel_requested(job) is True


def test_an_interrupted_run_reads_as_interrupted_and_not_as_nothing(core):
    """What a phone sees after the core it was watching went away. Not silence, and not a resume:
    "interrupted, start it again" is the answer an operator can act on."""
    from corparius.app import runs as app_runs
    from corparius.store import jobs as jobs_store

    _srv, port, store = core
    job = store.start_job(app_runs.KIND, "example", progress="tick 7")["id"]
    store.db.execute("UPDATE jobs SET owner_token='another-process' WHERE id=?", (job,))
    store.db.commit()
    assert store.interrupt_orphans() == [job]

    phone = Device(port, _pair(store))
    _status, seen = phone.jobs("example")
    mine = next(j for j in seen["jobs"] if j["id"] == job)
    assert mine["state"] == jobs_store.INTERRUPTED
    assert "tick 7" in mine["progress"], "and the progress it had reached survives"


# --- the surface, and what it is not ---------------------------------------------


def test_the_client_speaks_only_v1_and_the_meta_route(core):
    """A thin client that reached a legacy path would be pinning the console's internal shape, which is
    the thing versioning exists to stop. Read off this file so it stays true as it grows."""
    import pathlib
    import re

    source = pathlib.Path(__file__).read_text(encoding="utf-8")
    paths = set(re.findall(r'"(/api/[^"?]*)', source))
    assert paths, "the scan found nothing, so it proves nothing"
    assert all(p.startswith("/api/v1/") for p in paths), sorted(p for p in paths if "/v1/" not in p)


def test_it_refuses_a_core_that_speaks_a_different_version(core):
    """One refusal by version rather than one failure per request. A phone in an app store outlives the
    core it was written against, which is the whole reason `meta` carries three numbers."""
    from corparius.app import meta

    _srv, port, store = core
    conn = HTTPConnection("127.0.0.1", port, timeout=10)
    conn.request("GET", "/api/v1/meta")
    data = json.loads(conn.getresponse().read())
    conn.close()
    assert data["api_version"] == meta.API_VERSION == 1
    assert data["schema_version"] >= 21
    # Capabilities so a button is hidden rather than discovering a 404.
    assert data["capabilities"]["durable_jobs"] is True
    assert all(isinstance(v, bool) for v in data["capabilities"].values())


def test_nothing_here_imports_the_services_it_is_testing():
    """The rule that makes this an acceptance test rather than another unit test.

    Store handles appear in the fixture — a phone cannot pair itself, and `corparius pair` is a
    terminal command by design — but every *request* goes through a socket. An import of `app/` in the
    client would prove the services work, which other files already do; only HTTP proves the surface.
    """
    import pathlib
    import re

    source = pathlib.Path(__file__).read_text(encoding="utf-8")
    body = source[source.index("class Device") : source.index("@pytest.fixture()")]
    assert "HTTPConnection" in body
    assert not re.search(r"from corparius\.(app|store) import", body), (
        "the Device helper reaches past the wire"
    )
