#!/usr/bin/env python3
"""Per-file coverage ratchet: catch the drop a total cannot see.

`coverage report --fail-under=72` is necessary and not sufficient. It reads one number for
the whole package, and one number cannot see a module going from 88% to 30% while the total
holds — which is exactly what a restructuring does when a 2 000-line file splits and the
tests follow only some of the pieces.

Measured on this package at the time of writing: the total is 79.1% and the spread runs
from 16.0% (`integrations.py`) to 95%+ (`store.py`). A twelve-point fall in one module is
invisible in that average.

So each file carries its own floor, recorded in `tests/coverage-baseline.json`, and this
script fails when one falls more than `--tolerance` points below it.

Two rules that make it a ratchet rather than a wish:

- **A file with no baseline entry fails.** When a module splits, the new files have no
  floor and could be at 0% without anything noticing. Failing forces `--update`, which
  puts the new numbers in a diff a human reads.
- **A rise updates nothing automatically.** The baseline is only ever rewritten on purpose,
  so "it went up" cannot quietly become the new floor and then be lost again.

Usage:
    python packaging/coverage_ratchet.py            # check (what CI runs)
    python packaging/coverage_ratchet.py --update   # rewrite the baseline, deliberately

Expects `coverage.json` in the working directory — produce it with:
    coverage run -m pytest -q && coverage json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

BASELINE = Path("tests/coverage-baseline.json")
REPORT = Path("coverage.json")
# Five points, not the ten a reader might expect. A module whose tests moved with it does
# not lose five points; one that lost five lost tests.
DEFAULT_TOLERANCE = 5.0


def _normalise(path: str) -> str:
    """`corparius\\store.py` and `corparius/store.py` are the same file."""
    return path.replace("\\", "/")


def _read_report() -> dict[str, float]:
    if not REPORT.is_file():
        sys.exit(f"{REPORT} not found. Run: coverage run -m pytest -q && coverage json")
    data = json.loads(REPORT.read_text(encoding="utf-8"))
    return {
        _normalise(name): round(entry["summary"]["percent_covered"], 1)
        for name, entry in data["files"].items()
    }


def _read_baseline() -> dict[str, float]:
    if not BASELINE.is_file():
        sys.exit(f"{BASELINE} not found. Create it with --update, and read the diff.")
    return {_normalise(k): v for k, v in json.loads(BASELINE.read_text(encoding="utf-8")).items()}


def update() -> int:
    current = _read_report()
    BASELINE.parent.mkdir(parents=True, exist_ok=True)
    BASELINE.write_text(
        json.dumps(dict(sorted(current.items())), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"wrote {BASELINE} with {len(current)} files")
    print("Read the diff before committing: every number in it is a floor you are accepting.")
    return 0


def check(tolerance: float) -> int:
    current = _read_report()
    baseline = _read_baseline()

    undeclared = sorted(set(current) - set(baseline))
    vanished = sorted(set(baseline) - set(current))
    fell = [
        (name, baseline[name], current[name])
        for name in sorted(set(current) & set(baseline))
        if current[name] < baseline[name] - tolerance
    ]

    for name, was, now in fell:
        print(f"FELL  {name}: {was:.1f}% -> {now:.1f}%  (tolerance {tolerance:.0f} points)")
    for name in undeclared:
        print(f"NEW   {name}: {current[name]:.1f}% and no baseline entry")
    for name in vanished:
        print(f"GONE  {name}: in the baseline, not in the report")

    if fell or undeclared or vanished:
        print()
        print(
            "A total-only gate cannot see any of this. If these changes are intended, run\n"
            "  python packaging/coverage_ratchet.py --update\n"
            "and let the diff show which floors you are moving."
        )
        return 1

    risen = [(n, baseline[n], current[n]) for n in current if current[n] > baseline[n] + tolerance]
    for name, was, now in sorted(risen):
        print(f"rose  {name}: {was:.1f}% -> {now:.1f}%  (baseline unchanged until --update)")
    print(f"ok    {len(current)} files, none more than {tolerance:.0f} points below its floor")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--update", action="store_true", help="rewrite the baseline")
    parser.add_argument("--tolerance", type=float, default=DEFAULT_TOLERANCE)
    args = parser.parse_args(argv)
    return update() if args.update else check(args.tolerance)


if __name__ == "__main__":
    raise SystemExit(main())
