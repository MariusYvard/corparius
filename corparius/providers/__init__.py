"""Rank 3: the outside world, and the policy that decides which part of it to use.

Everything here talks to something that is not this process — a model API, an SMTP server, a
git remote, a deploy target, a lead source, the machine's own memory — or decides which of
those to reach for. That is the whole membership rule, and it is what makes the rank real:
below this line nothing knows the network exists; above it, nothing should have to.

Seventeen modules, and the folder is the point. `rank 3` used to be seventeen hand-maintained
entries in `tests/test_layers.py`; it is now derivable from the path, which is what the plan
meant by "les clés deviennent des chemins et les rangs cessent d'être une aspiration".

Two members are worth naming because they are not clients of anything:

  * `routing.py` decides which model a tier is pointed at, on measurements. It is here rather
    than in `domain/` because `claudecli.setup` calls it and `claudecli` is rank 3 — the layer
    rule outranked the plan's folder guess. It is also where the last of the five import
    cycles died.
  * `hardware.py` measures this machine. `ctypes.windll` on Windows, `os.sysconf` elsewhere,
    each attribute existing in only one set of stubs — which is why CI runs
    `mypy --platform win32` as a second leg, and why that leg has caught regressions in both
    directions.

No re-exports. A consumer imports the provider it needs, so `tests/test_layers.py` sees which
one — a forwarding `__init__` would make every caller look like it needed all seventeen, which
is the fact the tool-registry split existed to change.
"""
