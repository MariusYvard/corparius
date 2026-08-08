"""The transport. Rank 6, and nothing in the package imports this folder.

This was `webui.py`: 2 468 lines that were the operator console, its business logic, its
dotenv writer, its HTTP server and its route table at once — and that imported 33 of the 52
other modules, so importing the console loaded the whole product. Stage 6 of the
restructuring took it apart in two halves. The first moved nine use cases down into `app/`,
where a terminal can reach them, and that half is where the three live bugs were found. This
half is the leftover, and it is only transport:

```text
state      what the console keeps between requests — and loses on restart
contracts  Ctx and Route, the two shapes; data, not class hierarchies
adapters   the console's half of each use case, thin by construction
handlers   one function per endpoint, 57 of them, callable without a socket
routes     the table
server     the stdlib HTTP server and the checks before a handler runs
```

The imports run in exactly that order and never back. `contracts` is a separate module from
`routes` for that reason alone: a `Route` defined next to `ROUTES` would make `handlers`
import the table that imports it, which is the shape of all five cycles this restructuring
removed — and within one rank, ranks alone would not have caught it (`tests/test_layers.py`
carries `KNOWN_CYCLES` because of exactly that).

`serve` is re-exported because it is this package's entry point, named by `cli.py` and by the
frozen launcher. It is the one name outside `api/` that anything needs.
"""

from __future__ import annotations

from .server import build_server, serve

__all__ = ["build_server", "serve"]
