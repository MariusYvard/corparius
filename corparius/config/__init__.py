"""Rank 1: what the application is configured to be, before anything acts on it.

Everything here answers a question about *settings* — where a value comes from, what values
exist, which providers are registered, what an operator is allowed to change. Nothing here
calls a model, opens a socket or runs a command.

The rank matters in one direction in particular: rank 1 may not import the store, the
providers or the domain. `config/store_layer.py` is the declared exception, because reading
the settings table is one of the four layers and you cannot ask the database where the
database is.

No re-exports. A module here is imported by its own name, so `tests/test_layers.py` sees
every edge — a package `__init__` that forwards names is a compatibility facade the layer
rule cannot see through.
"""
