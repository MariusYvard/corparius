"""The business toolbox, in three files instead of one of 2 131 lines.

    spec.py      forty declarations, no callable, free to import
    effects.py   what each one does, and the adapters that requires
    registry.py  the two zipped together, by name

No re-exports here on purpose: a consumer imports the half it needs, so
`tests/test_layers.py` sees which half that is. A forwarding `__init__` would make every
consumer look like it needed the effects, which is the fact this split exists to change.
"""
