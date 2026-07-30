"""Stamp the package manifests with a released version and its real checksums.

Homebrew, Scoop and WinGet each carry a version and a SHA256 that have to match
an actual release asset. Nothing updated them, so after v0.2.0 shipped all three
still said `0.1.0`, and two of them still carried the literal string
`REPLACE_WITH_corparius-macos-arm64.zip_SHA256` — meaning anyone who ran
`brew install corparius` or `winget install` got a checksum mismatch, or nothing
at all. The files looked finished, which is why nobody looked.

Run by .github/workflows/release.yml after the binaries are built, from the
release's own SHA256SUMS, so the manifests cannot disagree with the assets they
point at. `tests/test_packaging_manifests.py` fails the build if they drift
again.

    python packaging/stamp_manifests.py 0.3.0 release/SHA256SUMS

Stdlib only, like everything else that has to run before dependencies exist.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PLACEHOLDER = "REPLACE_WITH_"


def read_sums(path: Path) -> dict[str, str]:
    """`SHA256SUMS` as {asset: digest}. The file is the output of many
    per-runner steps concatenated, so blank lines and stray whitespace are
    expected rather than a problem."""
    sums: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        parts = line.split()
        if len(parts) == 2 and re.fullmatch(r"[0-9a-f]{64}", parts[0]):
            sums[parts[1]] = parts[0]
    return sums


def _need(sums: dict[str, str], asset: str) -> str:
    digest = sums.get(asset)
    if not digest:
        raise SystemExit(
            f"no checksum for {asset} in SHA256SUMS (have: {', '.join(sorted(sums)) or 'nothing'})."
            "\nStamping a manifest with a missing digest would ship a broken install command."
        )
    return digest


def stamp(version: str, sums: dict[str, str], release_date: str = "") -> list[Path]:
    """Rewrite every manifest in place. Returns the files that changed.

    `release_date` is ISO `YYYY-MM-DD`; WinGet carries one and it had drifted
    eleven days behind the release it described, for the same reason as the
    version — nothing wrote it.
    """
    version = version.lstrip("v")
    changed = []

    # Homebrew cask (macOS, both architectures).
    cask = ROOT / "homebrew" / "corparius.rb"
    text = cask.read_text(encoding="utf-8")
    text = re.sub(r'version "[^"]*"', f'version "{version}"', text, count=1)
    for arch in ("arm64", "x64"):
        asset = f"corparius-macos-{arch}.zip"
        # Matches both the placeholder and a previously stamped digest, and is
        # anchored on the url line that follows so the two arches cannot swap.
        text = re.sub(
            rf'sha256 "[^"]*"(\s*\n\s*url "[^"]*{re.escape(asset)}")',
            lambda m, a=asset: f'sha256 "{_need(sums, a)}"{m.group(1)}',
            text,
            count=1,
        )
    changed += _write(cask, text)

    # Scoop (Windows). It templates `$version` into its urls and recomputes the
    # hash through `autoupdate`, so only the version needs stamping — but the
    # committed `hash` still has to be the one for this version or a fresh
    # install fails before autoupdate ever runs.
    scoop = ROOT / "scoop" / "corparius.json"
    data = json.loads(scoop.read_text(encoding="utf-8"))
    data["version"] = version
    exe = _need(sums, "corparius-windows-x64.exe")
    # Only the top-level `architecture` block. The one nested under `autoupdate`
    # keeps its literal `$version` and its hash-by-regex — that is the template
    # Scoop expands on the *next* release, and stamping it would freeze it.
    for spec in data.get("architecture", {}).values():
        spec["hash"] = exe
        spec["url"] = re.sub(r"/download/v[^/]+/", f"/download/v{version}/", spec["url"])
    changed += _write(scoop, json.dumps(data, indent=2, ensure_ascii=False) + "\n")

    # WinGet: three files, two of which carry the version.
    for name in (
        "MariusYvard.corparius.yaml",
        "MariusYvard.corparius.installer.yaml",
        "MariusYvard.corparius.locale.en-US.yaml",
    ):
        path = ROOT / "winget" / name
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        text = re.sub(r"^PackageVersion: .*$", f"PackageVersion: {version}", text, flags=re.M)
        text = re.sub(
            r"(InstallerUrl: \S*/download/v)[^/]+/", rf"\g<1>{version}/", text, flags=re.M
        )
        text = re.sub(r"^(\s*InstallerSha256: ).*$", rf"\g<1>{exe}", text, flags=re.M)
        if release_date:
            text = re.sub(r"^(ReleaseDate: ).*$", rf"\g<1>{release_date}", text, flags=re.M)
        changed += _write(path, text)

    return changed


def _today() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _write(path: Path, text: str) -> list[Path]:
    if path.read_text(encoding="utf-8") == text:
        return []
    path.write_text(text, encoding="utf-8")
    return [path]


def main(argv: list[str]) -> int:
    if not 3 <= len(argv) <= 4:
        print(__doc__)
        return 2
    version, sums_path = argv[1], Path(argv[2])
    release_date = argv[3] if len(argv) == 4 else _today()
    sums = read_sums(sums_path)
    if not sums:
        raise SystemExit(f"{sums_path} holds no checksums; refusing to stamp placeholders.")
    changed = stamp(version, sums, release_date)
    for path in changed:
        print(f"stamped {path.relative_to(ROOT.parent)}")
    if not changed:
        print(f"manifests already describe {version}")
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised through tests
    sys.exit(main(sys.argv))
