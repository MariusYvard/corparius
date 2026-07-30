# Packaging

Source of truth for how corparius is packaged and distributed.

## Standalone binaries

- `launcher.py` — the entry point of the frozen build (prepares the per-OS home,
  seeds the example company, serves the console). See `corparius/paths.py`.
- `corparius.spec` — the PyInstaller spec. Build locally with:

  ```bash
  pip install -r ../requirements-dev.txt
  pyinstaller corparius.spec --noconfirm
  ```

  CI builds and publishes these on a `v*` tag (`.github/workflows/release.yml`).

## Package managers

These manifests point at the GitHub Release assets. They are the upstream copy;
to actually distribute, submit each to its ecosystem (or host your own tap/bucket).

**You do not fill these in by hand.** The `stamp-manifests` job in
`.github/workflows/release.yml` rewrites the version, the checksums and WinGet's
`ReleaseDate` from the release's own `SHA256SUMS`, then commits them back — and
`tests/test_packaging_manifests.py` fails CI on a placeholder or a version that
disagrees with `corparius.__version__`.

That exists because the manual instructions that used to be here were not
followed: after v0.2.0 shipped, all three manifests still said `0.1.0` and two
still carried the literal `REPLACE_WITH_..._SHA256` where a checksum belongs, so
`brew install corparius` could not have worked. Documentation asking a human to
remember something before every release is a step that will be skipped.

| Manager | File | Notes |
| --- | --- | --- |
| Homebrew (macOS) | `homebrew/corparius.rb` | Cask, arm64 + Intel. `livecheck` tracks new releases; submit to homebrew-cask or a tap. |
| Scoop (Windows) | `scoop/corparius.json` | `checkver`/`autoupdate` refresh the version and hash from `SHA256SUMS` automatically. |
| winget (Windows) | `winget/MariusYvard.corparius.*.yaml` | Portable-type manifest set; submit to microsoft/winget-pkgs. Bump `PackageVersion` and `ReleaseDate` per release. |

Install, once published:

```bash
brew install --cask corparius        # macOS
scoop install corparius              # Windows (with the bucket added)
winget install MariusYvard.corparius # Windows
```

## Supply chain

- `../requirements.lock` — pinned, hash-checked dependency closure used by the
  Docker image and the CI binary builds. Regenerate with:

  ```bash
  pip install pip-tools
  pip-compile --generate-hashes --strip-extras --output-file ../requirements.lock ../requirements.txt
  ```

- The Docker base image is pinned by digest in `../Dockerfile`.
- The release workflow publishes SLSA build provenance for the image and an SPDX
  SBOM (image attestation + a `corparius-sbom.spdx.json` release asset).
