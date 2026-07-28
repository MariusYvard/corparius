"""Reachable is not capable.

The routing decided the trivial tier on one bit — did Ollama's port answer — and
then handed that tier a 9.6 GB model. On the machine this was written on, that
tier would have run at 8.6 tokens per second on the CPU: a 512-token draft in
just under a minute, on the *most* frequent tier in the roster.

The properties worth pinning are the ones that make the verdict trustworthy: it
never guesses when it does not know, it never decides on a number that changes
with the weather, and it never reports a speed it did not measure.
"""

import time

from corparius import hardware
from corparius.store import Store

GB = 1_000_000_000


def test_specs_never_raises_and_reports_cores():
    """Called on every platform CI runs. A probe that throws takes the doctor
    down with it."""
    s = hardware.specs()
    assert set(s) == {"cores", "ram_total", "ram_available"}
    assert s["cores"] is None or s["cores"] >= 1


def test_undetectable_memory_is_none_not_zero(monkeypatch):
    """None and 0 mean opposite things. A consumer that reads "I don't know" as
    "there is none" refuses local inference on a machine that could run it."""
    monkeypatch.setattr(hardware, "_windows_memory", lambda: (None, None))
    monkeypatch.setattr(hardware, "_posix_memory", lambda: (None, None))
    s = hardware.specs()
    assert s["ram_total"] is None and s["ram_available"] is None
    assert hardware.fits(2 * GB, s) is None, "unknown memory must not read as 'does not fit'"


def test_a_response_without_durations_yields_no_verdict():
    """Ollama times its own generation. A server that does not report it gets a
    refusal, not a number derived from this process's clock — that would fold in
    queueing and the network and overstate how slow the machine is."""
    out = hardware.parse_timings({"eval_count": 40})
    assert out["ok"] is False and "eval_duration" in out["detail"]
    assert "tokens_per_second" not in out


def test_timings_are_read_from_the_fields_ollama_sends():
    out = hardware.parse_timings(
        {"eval_count": 11, "eval_duration": 1_280_000_000, "load_duration": 6_920_000_000}
    )
    assert out["ok"] and out["tokens_per_second"] == 8.6 and out["load_seconds"] == 6.92


def test_a_zero_duration_is_not_a_division_by_zero():
    assert hardware.parse_timings({"eval_count": 11, "eval_duration": 0})["ok"] is False


def test_fit_is_judged_against_total_memory_not_free_memory():
    """Free memory is the weather, not the climate: measured on one machine an
    hour apart it went 4.0 GB -> 1.9 GB purely because a test suite was running.
    A verdict that flips with that is not a verdict."""
    busy = {"cores": 8, "ram_total": 17 * GB, "ram_available": 1 * GB}
    idle = {"cores": 8, "ram_total": 17 * GB, "ram_available": 9 * GB}
    assert hardware.fits(5 * GB, busy) == hardware.fits(5 * GB, idle) is True


def test_a_model_larger_than_the_machine_does_not_fit():
    small = {"cores": 4, "ram_total": 8 * GB, "ram_available": 6 * GB}
    assert hardware.fits(9.6 * GB, small) is False


def test_tightness_is_reported_but_never_decides():
    """Loading it now would evict something — worth saying, not worth refusing."""
    busy = {"cores": 8, "ram_total": 17 * GB, "ram_available": 1 * GB}
    assert hardware.tight(5 * GB, busy) is True
    assert hardware.fits(5 * GB, busy) is True


def test_the_speed_verdict_quotes_its_arithmetic():
    """An operator can disagree with a threshold. They cannot disagree with
    "at 8.6 tokens/s a 512-token draft takes 59.5s"."""
    out = hardware.verdict({"tokens_per_second": 8.6, "placement": "cpu"}, min_tokens_per_second=15)
    assert out["ok"] is False
    assert "8.6 tokens/s" in out["reason"] and "59.5s" in out["reason"]
    assert "CPU" in out["reason"]


def test_a_fast_machine_passes():
    out = hardware.verdict(
        {"tokens_per_second": 40.0, "placement": "gpu"}, min_tokens_per_second=15
    )
    assert out["ok"] is True and "40.0 tokens/s" in out["reason"]


def test_not_measured_is_its_own_answer():
    """Not "incapable" — nobody has looked. The reason has to say what to run."""
    out = hardware.verdict(None)
    assert out["ok"] is False and "corparius bench" in out["reason"]


def test_a_model_that_cannot_fit_is_refused_without_any_measurement():
    """The memory question is answered from specs alone, before anything runs."""
    out = hardware.verdict(None, model_size=999 * GB)
    assert out["ok"] is False and "in total" in out["reason"]


def test_a_measurement_with_no_throughput_is_refused():
    assert hardware.verdict({"tokens_per_second": 0})["ok"] is False


def test_the_configured_model_wins_when_it_fits():
    models = [{"name": "gemma:2b", "size": 1 * GB}, {"name": "gemma4:e4b", "size": 3 * GB}]
    spec = {"cores": 8, "ram_total": 17 * GB, "ram_available": 8 * GB}
    assert hardware.best_local_model(models, prefer="gemma4:e4b", spec=spec) == "gemma4:e4b"


def test_a_family_prefix_does_not_match_a_different_model():
    """gemma4:e4b and gemma4:12b share a family and are different models of
    different sizes. Matching on the family alone answered the first with the
    second."""
    models = [{"name": "gemma4:12b", "size": 7 * GB}, {"name": "gemma4:e4b", "size": 9 * GB}]
    spec = {"cores": 8, "ram_total": 32 * GB, "ram_available": 16 * GB}
    assert hardware.best_local_model(models, prefer="gemma4:e4b", spec=spec) == "gemma4:e4b"


def test_a_bare_family_name_still_matches():
    models = [{"name": "gemma4:12b", "size": 7 * GB}]
    spec = {"cores": 8, "ram_total": 32 * GB, "ram_available": 16 * GB}
    assert hardware.best_local_model(models, prefer="gemma4", spec=spec) == "gemma4:12b"


def test_the_largest_that_fits_wins_when_the_preference_is_absent():
    """Within what memory allows, a bigger model is a better one and the
    operator already paid the disk for it."""
    models = [{"name": "small", "size": 1 * GB}, {"name": "big", "size": 6 * GB}]
    spec = {"cores": 8, "ram_total": 17 * GB, "ram_available": 8 * GB}
    assert hardware.best_local_model(models, prefer="absent:1b", spec=spec) == "big"


def test_nothing_fits_is_an_empty_string_not_a_guess():
    spec = {"cores": 2, "ram_total": 4 * GB, "ram_available": 1 * GB}
    assert hardware.best_local_model([{"name": "huge", "size": 40 * GB}], spec=spec) == ""


def test_an_unmeasurable_machine_does_not_disqualify_every_model():
    """fits() is None there, and None must not filter the model out."""
    spec = {"cores": 8, "ram_total": None, "ram_available": None}
    assert hardware.best_local_model([{"name": "m", "size": 3 * GB}], spec=spec) == "m"


def test_the_profile_round_trips_through_the_store(tmp_path):
    store = Store(str(tmp_path))
    assert hardware.profile(store) is None, "nothing measured yet is None, not a default"
    store.save_machine(
        {
            "cores": 8,
            "ram_total": 17 * GB,
            "ram_available": 4 * GB,
            "tokens_per_second": 8.6,
            "load_seconds": 6.9,
            "placement": "cpu",
            "model": "gemma:2b",
        }
    )
    prof = hardware.profile(store)
    assert prof["tokens_per_second"] == 8.6 and prof["placement"] == "cpu"
    assert prof["stale"] is False and prof["age_days"] == 0.0


def test_a_stale_profile_is_flagged_not_discarded(tmp_path, monkeypatch):
    """Silently reusing a year-old number and silently throwing it away are both
    worse than saying how old it is."""
    store = Store(str(tmp_path))
    store.save_machine({"tokens_per_second": 8.6, "placement": "cpu", "model": "gemma:2b"})
    sixty_days_on = time.time() + 60 * 86400
    monkeypatch.setattr(hardware.time, "time", lambda: sixty_days_on)
    prof = hardware.profile(store, max_age_days=30)
    assert prof["stale"] is True and prof["tokens_per_second"] == 8.6


def test_only_one_machine_row_ever_exists(tmp_path):
    store = Store(str(tmp_path))
    for speed in (8.6, 40.0):
        store.save_machine({"tokens_per_second": speed, "placement": "cpu", "model": "m"})
    assert store.db.execute("SELECT COUNT(*) FROM machine").fetchone()[0] == 1
    assert store.load_machine()["tokens_per_second"] == 40.0


def test_measure_survives_an_unreachable_ollama(monkeypatch):
    import requests

    def down(*a, **k):
        raise requests.RequestException("connection refused")

    monkeypatch.setattr(hardware.requests, "post", down)
    out = hardware.measure("gemma:2b", timeout=1)
    assert out["ok"] is False and "did not answer" in out["detail"]
