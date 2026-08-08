"""`python -m corparius.cli`, which the port-in-use message tells operators to type.

A module could carry its own `if __name__ == "__main__"`; a package needs this file, and the
error when it is missing ("No module named corparius.cli.__main__") names nothing an operator
could act on.
"""

from __future__ import annotations

from . import main

raise SystemExit(main())
