"""Replace the running binary with the newest release, on a button.

This is the one place in corparius that downloads code and then runs it, so the
whole module is built around not doing that carelessly:

  * It only works from a frozen build. From source or Docker there is nothing to
    replace, and it says so instead of doing something surprising.
  * The download is checked against the SHA256SUMS published beside it, before
    anything on disk is touched. A mismatch is a refusal, never a warning.
  * The old binary is renamed rather than deleted, and it stays until the new
    one has started once. A failure at any step puts the old name back.

Nothing here goes near a company. The executable and the data live in different
places by design — the data in a per-OS folder resolved by paths.py, the binary
wherever the operator dropped it — and every path this module writes to is the
binary's own name plus a suffix. A test drives a real update over a home full of
companies and requires every byte of it to be identical afterwards.

Belt and braces anyway, because the cost of being wrong here is somebody's
business: a backup is taken before the swap, the one `corparius backup` already
writes, and the update refuses outright if the thing it would replace contains
the data folder. Losing a binary is a re-download. Losing a company is not.

What the checksum proves and does not prove: it proves the bytes that arrived
are the bytes GitHub serves. It does not prove who built them, because the sums
file lives in the same release — anyone who could publish one could publish the
other. Real provenance needs a signing key, which these builds do not have; the
Docker image is the signed path (SLSA attestation on GHCR). Said plainly here
because an operator pressing an update button deserves to know which of the two
guarantees they are getting.
"""

from __future__ import annotations

import hashlib
import os
import platform
import re
import shutil
import sys
import zipfile
from pathlib import Path

import requests

from .kernel import paths
from .update_check import RELEASES_URL

DOWNLOAD_BASE = "https://github.com/MariusYvard/corparius/releases/download"
SUMS = "SHA256SUMS"
OLD_SUFFIX = ".old"
NEW_SUFFIX = ".new"
TIMEOUT = 120


class UpdateError(Exception):
    """A refusal an operator can act on, in one sentence."""


def asset_name() -> str | None:
    """The release asset for this machine, or None if we do not publish one.

    Named from the running interpreter rather than from a stored setting: an
    operator who copied a Windows build onto a Mac should get a refusal, not a
    download of the wrong file.
    """
    machine = platform.machine().lower()
    if sys.platform == "win32":
        return "corparius-windows-x64.exe" if machine in ("amd64", "x86_64") else None
    if sys.platform == "darwin":
        return "corparius-macos-arm64.zip" if machine == "arm64" else "corparius-macos-x64.zip"
    if sys.platform.startswith("linux"):
        return "corparius-linux-x64" if machine in ("x86_64", "amd64") else None
    return None


def target() -> Path:
    """What gets replaced: the .app bundle on macOS, the executable elsewhere.

    On macOS the running file is buried at Contents/MacOS/corparius inside a
    bundle, and swapping that one file leaves a bundle whose Info.plist and
    resources belong to the old version.
    """
    exe = Path(sys.executable).resolve()
    for parent in exe.parents:
        if parent.suffix == ".app":
            return parent
    return exe


def why_not() -> str:
    """Empty when an update can be applied here; otherwise the reason."""
    if not paths.is_frozen():
        return (
            "this is not the downloadable build. From source, `git pull` and restart; "
            "in Docker, `docker pull ghcr.io/mariusyvard/corparius` and recreate the "
            "container."
        )
    if asset_name() is None:
        return (
            f"no release is published for {sys.platform}/{platform.machine()}. See {RELEASES_URL}."
        )
    spot = target()
    # The only shape in which replacing the binary could take data with it: a
    # macOS bundle, which is a directory, holding the operator's home. It should
    # never happen — paths.py puts the home under Application Support — but the
    # swap deletes and moves directories, and "should never happen" is not the
    # standard for something that would take a company with it.
    if spot.is_dir():
        for data in (paths.user_home(), Path(_data_path())):
            try:
                data.resolve().relative_to(spot.resolve())
            except ValueError:
                continue
            return (
                f"your data lives inside {spot}, which is what an update replaces. "
                "Move corparius out of your data folder, or update it by hand. "
                "Nothing was touched."
            )
    if not os.access(spot.parent, os.W_OK):
        return (
            f"{spot.parent} is not writable by this user. Move corparius somewhere you own "
            "(your home folder), or update it by hand."
        )
    return ""


def _data_path() -> str:
    from .config import Settings

    return Settings().data_path


def _get(url: str) -> bytes:
    try:
        r = requests.get(url, timeout=TIMEOUT)
        r.raise_for_status()
        return r.content
    except requests.RequestException as exc:
        raise UpdateError(f"could not download {url.rsplit('/', 1)[-1]}: {exc}") from exc


def expected_sum(sums_text: str, name: str) -> str:
    """The line for one asset out of SHA256SUMS. Missing is a refusal: an asset
    nobody published a sum for is an asset nobody vouched for."""
    for line in sums_text.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[1] == name:
            return parts[0].lower()
    raise UpdateError(f"{SUMS} has no line for {name}; refusing to install it")


TAG = re.compile(r"v?\d+(?:\.\d+){0,3}\Z")


def check_tag(tag: str) -> str:
    """A release tag, or a refusal. Nothing else may reach the download URL.

    `..` in this string used to walk the URL out of the repository: requests
    normalises dot segments while preparing a request, so DOWNLOAD_BASE pinned
    nothing. And the checksum could not catch it, because SHA256SUMS came from
    the same redirected directory — the verification agreed with itself.

    Callers should pass the tag update_check reported rather than one a user
    typed. This is the second lock on that door, not the first.
    """
    clean = tag.strip()
    if not TAG.match(clean):
        raise UpdateError(f"{tag!r} is not a release tag; refusing to download anything")
    return clean


def fetch(tag: str, name: str) -> bytes:
    """Download the asset and prove it against the published sum. Nothing has
    touched the disk when this returns, and nothing will if it raises."""
    tag = check_tag(tag)
    sums = _get(f"{DOWNLOAD_BASE}/{tag}/{SUMS}").decode("utf-8", "replace")
    want = expected_sum(sums, name)
    blob = _get(f"{DOWNLOAD_BASE}/{tag}/{name}")
    got = hashlib.sha256(blob).hexdigest()
    if got != want:
        raise UpdateError(
            f"checksum mismatch for {name}: expected {want[:16]}…, got {got[:16]}…. "
            "Nothing was installed."
        )
    return blob


def _write_payload(blob: bytes, name: str, destination: Path) -> None:
    """Put the new build at `destination`, which does not exist yet."""
    if name.endswith(".zip"):
        staging = destination.parent / (destination.name + ".staging")
        shutil.rmtree(staging, ignore_errors=True)
        staging.mkdir(parents=True)
        archive = staging / "asset.zip"
        archive.write_bytes(blob)
        with zipfile.ZipFile(archive) as zf:
            zf.extractall(staging)
        archive.unlink()
        inner = next((p for p in staging.iterdir() if p.suffix == ".app"), None)
        if inner is None:
            shutil.rmtree(staging, ignore_errors=True)
            raise UpdateError("the downloaded archive holds no .app bundle")
        shutil.move(str(inner), str(destination))
        shutil.rmtree(staging, ignore_errors=True)
        return
    destination.write_bytes(blob)
    destination.chmod(destination.stat().st_mode | 0o111)


def _discard(path: Path) -> None:
    if path.is_dir():
        shutil.rmtree(path, ignore_errors=True)
    elif path.exists():
        path.unlink(missing_ok=True)


def apply(tag: str) -> dict:
    """Swap in the new build. Returns what to tell the operator.

    The order is the whole safety story, and it is: verify, back up, stage, then
    two renames.

    Writing the new build to `<name>.new` first, beside the old one, means the
    moment where no corparius exists at that path is two rename syscalls wide
    instead of a whole download-and-write. Both renames are on one filesystem,
    so each is atomic. A running executable cannot be deleted on Windows but it
    can be renamed, which is why the old build is moved rather than removed —
    and why it is still there to put back when anything fails.
    """
    blocked = why_not()
    if blocked:
        raise UpdateError(blocked)
    name = asset_name()
    assert name is not None  # why_not() refused otherwise
    blob = fetch(tag, name)  # nothing has touched the disk if this raises

    saved = _backup()
    spot = target()
    old = spot.parent / (spot.name + OLD_SUFFIX)
    staged = spot.parent / (spot.name + NEW_SUFFIX)
    _discard(old)
    _discard(staged)
    _write_payload(blob, name, staged)  # the slow part, while the old one still runs

    os.replace(spot, old)
    try:
        os.replace(staged, spot)
    except OSError as exc:
        os.replace(old, spot)  # put the operator back where they started
        _discard(staged)
        raise UpdateError(
            f"could not put the new build in place, the old one is back: {exc}"
        ) from exc
    return {
        "ok": True,
        "installed": tag.lstrip("vV"),
        "path": str(spot),
        "previous": str(old),
        "backup": saved,
        "restart": True,
    }


def _backup() -> str:
    """A snapshot of the store and the companies, before anything moves.

    An update cannot reach them — different folder, and every path written here
    is the binary's own name plus a suffix — so this is insurance against a
    mistake in this file rather than against a known risk. It reuses the zip
    `corparius backup` already writes, and a failure to take it does not stop
    the update: refusing to update because a backup could not be written would
    trade a real problem for a hypothetical one.
    """
    try:
        from . import backup

        return str(backup.make_backup(_data_path()))
    except Exception:  # noqa: BLE001 - insurance, never the reason a launch fails
        return ""


def sweep_previous() -> None:
    """Clear what the last update left behind, once.

    Called at startup, so it only runs after the new build has proved it
    starts — which is the point of keeping the old one rather than deleting it
    during the swap. A stale `.new` goes too: it means a crash between staging
    and the rename, and leaving it would make the next update think it had
    already downloaded something.

    Never a reason a launch fails, and never anything but these two names.
    """
    if not paths.is_frozen():
        return
    try:
        spot = target()
        for leftover in (
            spot.parent / (spot.name + OLD_SUFFIX),
            spot.parent / (spot.name + NEW_SUFFIX),
        ):
            _discard(leftover)
    except OSError:
        pass  # locked or not ours: it costs one file, not a launch
