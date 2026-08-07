"""Rank 5: the use cases, with no transport attached.

Everything here is something the product *does* — write a setting, start a run, apply a
decision — expressed so that both callers can reach it. There are two, and only one of them
existed before: the console, and the command line.

Two rules, and `tests/test_app_layer.py` holds both:

  * **No `Ctx` parameter, ever.** `Ctx` carries an HTTP request — a body, headers, a query
    string. A service taking one is a route handler that has been moved to a different folder,
    which is the failure mode this whole stage is trying to avoid. Signatures are explicit:
    `(store, env_file, values)`, not `(state)` and not `(ctx)`.
  * **No transport error, ever.** A service that raises the console's 400 cannot be called by
    anything else. It raises what the failure actually is, and the route translates. The
    pattern already exists one layer down: `kernel/dotenv.merge` raises `LineBreakRefused` and
    `webui._merge_env_file` turns it into a status code.

The measured reason this folder exists: the business logic lived in HTTP handlers, so the
console could do eleven things the CLI could not — write a setting, chat with the CEO, edit a
backlog task, apply a directive among them. On a headless box that meant editing .env by hand.
"""
