"""The CI and release workflows, checked for the mistakes that have actually
happened here rather than for style.

Three of them cost a release or a broken install:

- a `run:` block containing a literal backslash-n instead of a newline, from a
  shell heredoc eating the escape while the file was being written. YAML is
  happy, the shell is not, and nothing runs until someone tags a release.
- a job pinned to a runner image GitHub had retired (`macos-13`): the job did
  not fail, it queued forever for a runner that no longer exists and held the
  whole release behind it.
- a `download-artifact` with no `pattern`, which pulled the buildx build record
  the docker job uploads on its own and failed after five retries.

None of these are visible in review. All three are cheap to check.
"""

import re
from pathlib import Path

import pytest
import yaml

WORKFLOWS = Path(".github/workflows")

pytestmark = pytest.mark.skipif(not WORKFLOWS.is_dir(), reason="a wheel install without .github/")


def _files():
    return sorted(WORKFLOWS.glob("*.yml")) + sorted(WORKFLOWS.glob("*.yaml"))


def _steps(doc):
    for job in (doc.get("jobs") or {}).values():
        yield from job.get("steps") or []


def test_every_workflow_parses():
    for path in _files():
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert isinstance(doc, dict) and doc.get("jobs"), path


def test_no_run_block_contains_a_literal_backslash_n():
    """The heredoc bug. `python x.py \\n  "$(date)"` is valid YAML, a valid
    string, and a shell command that fails — and it only fails on a tag."""
    offenders = []
    for path in _files():
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        for step in _steps(doc):
            script = step.get("run") or ""
            if "\\n" in script:
                offenders.append(f"{path} :: {step.get('name') or script[:40]}")
    assert not offenders, "literal \\n in a shell block:\n  " + "\n  ".join(offenders)


def test_no_job_targets_a_retired_runner_image():
    """`macos-13` was the Intel image; GitHub retired it and the release job sat
    in the queue for a runner that would never come. Bare `macos-latest` moves
    under you, which for a PyInstaller build changes the minimum macOS a user
    needs — so that is named here too."""
    retired = {"macos-13", "macos-12", "macos-11", "ubuntu-20.04", "ubuntu-18.04", "windows-2019"}
    seen = set()
    for path in _files():
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        for job in doc["jobs"].values():
            runs_on = job.get("runs-on")
            if isinstance(runs_on, str) and not runs_on.startswith("${{"):
                seen.add(runs_on)
            for entry in ((job.get("strategy") or {}).get("matrix") or {}).get("include") or []:
                if isinstance(entry.get("os"), str):
                    seen.add(entry["os"])
    assert not (seen & retired), f"retired runner image(s): {sorted(seen & retired)}"


def test_every_artifact_download_names_what_it_wants():
    """Without a pattern, `download-artifact` also pulls the buildx build record
    that `docker/build-push-action` uploads on its own — an artifact the release
    job never reads, and the one whose download failed after five retries and
    took the release down with it."""
    for path in _files():
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        for step in _steps(doc):
            uses = step.get("uses") or ""
            if uses.startswith("actions/download-artifact"):
                with_ = step.get("with") or {}
                assert with_.get("pattern") or with_.get("name"), f"{path}: {step}"


def test_the_release_still_guards_the_version_and_the_tests():
    """Two gates that must not be quietly dropped: the tag has to match
    `corparius.__version__`, and the suite has to pass on the tag itself rather
    than on some earlier run."""
    doc = yaml.safe_load((WORKFLOWS / "release.yml").read_text(encoding="utf-8"))
    assert "version-guard" in doc["jobs"] and "test" in doc["jobs"]
    for name in ("docker", "native"):
        assert "test" in doc["jobs"][name]["needs"], name
        assert "version-guard" in doc["jobs"][name]["needs"], name


def test_the_manifests_are_stamped_after_the_release_not_before():
    """Stamping needs the published SHA256SUMS, so it cannot run until the
    release exists — and it has to be able to push the result back."""
    doc = yaml.safe_load((WORKFLOWS / "release.yml").read_text(encoding="utf-8"))
    job = doc["jobs"]["stamp-manifests"]
    assert "github-release" in job["needs"]
    assert job["permissions"]["contents"] == "write"
    # Checked out from the default branch: the tag is detached, and a commit
    # made there would land nowhere anyone reads.
    checkout = next(
        s for s in job["steps"] if str(s.get("uses", "")).startswith("actions/checkout")
    )
    assert "default_branch" in str(checkout.get("with", {}).get("ref", ""))


def test_ci_runs_the_type_checker_on_both_platforms():
    """`ctypes.windll` type-checks only with the Windows stubs and `os.sysconf`
    only with the POSIX ones, so a single-platform mypy run passes locally and
    fails for the next person on the other OS."""
    text = (WORKFLOWS / "ci.yml").read_text(encoding="utf-8")
    assert re.search(r"mypy\b(?!.*--platform)", text), "no plain mypy run"
    assert "--platform win32" in text, "mypy never runs with the Windows stubs"
