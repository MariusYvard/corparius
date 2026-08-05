"""Rank 0: the floor.

Nothing here imports anything else from corparius — not a lower rank, nothing. That is the
whole property, and it is what makes these modules safe to import from any layer without
thinking about it. `tests/test_layers.py` enforces it, and `tests/test_import_cost.py`
asserts that importing any of them costs nothing beyond the standard library.

See docs/architecture-code.md for the ranks, and docs/adr/0007 for the decision.
"""
