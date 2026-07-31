"""The install commands in the README have to actually work.

`packaging/` ships a Homebrew cask, a Scoop manifest and a WinGet manifest.
Nothing updated them, so after v0.2.0 shipped all three still said `0.1.0`, and
two still carried the literal string `REPLACE_WITH_corparius-macos-arm64.zip_SHA256`
where a checksum belongs. `brew install corparius` could not have worked. The
files looked finished, which is exactly why nobody looked.

So: the release workflow stamps them from the release's own SHA256SUMS, and
these tests refuse a placeholder or a version that disagrees with the package.
"""

import json
import re
from pathlib import Path

import pytest

from corparius import __version__

PACKAGING = Path("packaging")
CASK = PACKAGING / "homebrew" / "corparius.rb"
SCOOP = PACKAGING / "scoop" / "corparius.json"
WINGET = PACKAGING / "winget"

pytestmark = pytest.mark.skipif(not PACKAGING.is_dir(), reason="a wheel install without packaging/")


def _manifests():
    return [CASK, SCOOP, *sorted(WINGET.glob("*.yaml"))]


def test_no_manifest_still_carries_a_placeholder_where_a_checksum_belongs():
    """The failure that shipped. A cask whose sha256 is the word REPLACE_WITH is
    not a draft, it is an install command that fails on the user's machine."""
    offenders = [
        f"{p}: {line.strip()}"
        for p in _manifests()
        for line in p.read_text(encoding="utf-8").splitlines()
        if "REPLACE_WITH" in line
    ]
    assert not offenders, "\n".join(offenders)


def test_every_declared_checksum_is_a_real_sha256():
    """Catches a half-stamped file: the right shape, the wrong length."""
    for path in _manifests():
        for groups in re.findall(
            r'sha256 "([^"]+)"|"hash": "([^"]+)"|InstallerSha256: (\S+)',
            path.read_text(encoding="utf-8"),
        ):
            digest = next(v for v in groups if v)
            assert re.fullmatch(r"[0-9a-fA-F]{64}", digest), f"{path}: {digest!r}"


def _declared():
    """The version each manifest says it installs."""
    found = {}
    found[str(CASK)] = re.search(r'version "([^"]+)"', CASK.read_text(encoding="utf-8")).group(1)
    found[str(SCOOP)] = json.loads(SCOOP.read_text(encoding="utf-8"))["version"]
    for path in sorted(WINGET.glob("*.yaml")):
        match = re.search(r"^PackageVersion: (\S+)$", path.read_text(encoding="utf-8"), re.M)
        if match:
            found[str(path)] = match.group(1)
    return found


def _tuple(version: str):
    return tuple(int(p) for p in re.findall(r"\d+", version))


def test_no_manifest_is_ahead_of_the_package_or_disagrees_with_the_others():
    """The manifests describe the **latest published release**, not the working
    tree. Between bumping `__version__` and the release actually shipping, they
    legitimately name the previous version — that is the truth, not drift, and
    the `stamp-manifests` job moves them forward once the assets exist.

    This checked `== __version__` at first, which would have failed CI on main
    the moment anyone bumped the version, before a release could possibly have
    run. What actually has to hold: never ahead of the code, and all of them
    agreeing with each other, because they install the same program.
    """
    found = _declared()
    assert found, "no manifest declares a version at all"
    assert len(set(found.values())) == 1, f"the manifests disagree: {found}"

    declared = next(iter(found.values()))
    assert _tuple(declared) <= _tuple(__version__), (
        f"manifests say {declared}, which is ahead of corparius {__version__} — "
        "they would install something that does not exist"
    )


def test_every_download_url_points_at_the_version_its_own_manifest_declares():
    """The version field and the url can drift apart independently, and only the
    url decides what a user actually downloads. Anchored on each manifest's own
    declared version rather than on `__version__`, for the reason above."""
    found = _declared()
    for path in _manifests():
        text = path.read_text(encoding="utf-8")
        declared = found.get(str(path)) or next(iter(found.values()))
        for tag in re.findall(r"/releases/download/v([^/]+)/", text):
            # Scoop's autoupdate block keeps a literal $version template; that is
            # the point of it, and it must survive stamping.
            assert tag in (declared, "$version", "#{version}"), (
                f"{path} declares v{declared} but downloads v{tag}"
            )


def test_stamping_a_copy_produces_valid_manifests(tmp_path):
    """Runs the real script against a copy, so the regexes are exercised rather
    than assumed. Idempotent, because the release workflow may retry."""
    import importlib.util
    import shutil

    work = tmp_path / "packaging"
    shutil.copytree(PACKAGING, work, ignore=shutil.ignore_patterns("__pycache__"))

    spec = importlib.util.spec_from_file_location("stamp_manifests", work / "stamp_manifests.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    digest = "a" * 64
    sums = {
        "corparius-macos-arm64.zip": digest,
        "corparius-macos-x64.zip": "b" * 64,
        "corparius-windows-x64.exe": "c" * 64,
    }
    module.stamp("9.9.9", sums)

    cask = (work / "homebrew" / "corparius.rb").read_text(encoding="utf-8")
    assert 'version "9.9.9"' in cask and "REPLACE_WITH" not in cask
    # The two architectures must not have swapped: each sha256 sits above the
    # url it belongs to, and the regex is anchored on that.
    arm = re.search(r'sha256 "([^"]+)"\s*\n\s*url "[^"]*arm64', cask).group(1)
    intel = re.search(r'sha256 "([^"]+)"\s*\n\s*url "[^"]*x64', cask).group(1)
    assert arm == "a" * 64 and intel == "b" * 64

    scoop = json.loads((work / "scoop" / "corparius.json").read_text(encoding="utf-8"))
    assert scoop["version"] == "9.9.9"
    assert scoop["architecture"]["64bit"]["hash"] == "c" * 64
    assert "/v9.9.9/" in scoop["architecture"]["64bit"]["url"]
    # The autoupdate template survives, or the next release cannot self-update.
    assert "$version" in scoop["autoupdate"]["architecture"]["64bit"]["url"]

    installer = (work / "winget" / "MariusYvard.corparius.installer.yaml").read_text(
        encoding="utf-8"
    )
    assert "PackageVersion: 9.9.9" in installer
    assert f"InstallerSha256: {'c' * 64}" in installer
    assert "/v9.9.9/" in installer

    # Idempotent: a retried release step must not corrupt what it already wrote.
    before = {p: p.read_bytes() for p in work.rglob("*") if p.is_file()}
    module.stamp("9.9.9", sums)
    assert {p: p.read_bytes() for p in work.rglob("*") if p.is_file()} == before


def test_a_missing_checksum_stops_the_release_instead_of_shipping_a_lie(tmp_path):
    """Stamping a manifest with a digest that is not there would produce a file
    that looks stamped and installs nothing."""
    import importlib.util
    import shutil

    work = tmp_path / "packaging"
    shutil.copytree(PACKAGING, work, ignore=shutil.ignore_patterns("__pycache__"))
    spec = importlib.util.spec_from_file_location("stamp_manifests", work / "stamp_manifests.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    with pytest.raises(SystemExit, match="no checksum"):
        module.stamp("9.9.9", {"corparius-macos-arm64.zip": "a" * 64})


def test_sha256sums_is_parsed_the_way_the_release_actually_writes_it(tmp_path):
    """Concatenated from one file per runner, so blank lines and CRLF are
    normal rather than a malformed input."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "stamp_manifests", PACKAGING / "stamp_manifests.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    path = tmp_path / "SHA256SUMS"
    path.write_text(
        f"{'a' * 64}  corparius-linux-x64\r\n\n{'b' * 64}  corparius-windows-x64.exe\n",
        encoding="utf-8",
    )
    assert module.read_sums(path) == {
        "corparius-linux-x64": "a" * 64,
        "corparius-windows-x64.exe": "b" * 64,
    }
