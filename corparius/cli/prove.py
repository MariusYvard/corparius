"""Proving that a configured thing can actually be called. Rank 6.

Four commands and one purpose: the difference between a key being set and a model answering.
`preflight` makes real calls per tier, `bench` measures what this machine can run locally,
`claude` checks the subscription CLI's login, `mail` sends and reads one message. None of them
guesses — every one of them is the reason `corparius doctor` can stay cheap and this can be
expensive.

This is where the project's rule about polled endpoints comes from the other side: these are
the network probes, and they run when an operator asks for them.
"""

from __future__ import annotations

import json

from ..app.support import open_store
from ..config.settings import Settings


def cmd_mail(args) -> int:
    """Prove the mail account, from a terminal.

    Nothing in the CLI sent a test message. `doctor` reports whether the settings are *present*,
    which on a headless box is the difference between believing the mail is wired and knowing
    it — and this project's discipline is the second one. The console had the button; the machine
    that most needs it did not.

    It spends a real message, and it says so: that is the bargain `integrations.smtp_check`
    documents, because nothing cheaper actually proves the setup.
    """
    from ..app import mail as app_mail

    if args.steps:
        for provider, steps in sorted(app_mail.steps().items()):
            print(provider)
            for step in steps:
                mark = " " if not step["checkable"] else ("x" if step["done"] else " ")
                text = step["fr"] if args.lang.startswith("fr") else step["en"]
                note = "" if step["checkable"] else "   (corparius cannot check this one)"
                print(f"  [{mark}] {text}{note}")
        return 0
    out = app_mail.check(args.to, lang=args.lang)
    print(out["detail"])
    if not out["ok"]:
        # The service's copy says "below" and "above": it was written for the settings page, and
        # a terminal has no below. Rather than rewrite strings the console also shows, say the
        # thing a terminal can act on — which is a command that exists now.
        print()
        print("set them with: corparius set CORP_SMTP_HOST=... CORP_SMTP_USER=...")
        print("what is left, per provider: corparius mail --steps")
    return 0 if out["ok"] else 1


def cmd_preflight(args) -> None:
    """Call each configured model for real, eight tokens each, and say which
    ones this account can actually use.

    A catalogue lists models that exist. It does not list models *you* may call:
    a paid tier you are not on, a preview you were never granted, a region your
    account is not in — all of them appear in `/models` and answer 404 to you.
    Routing off that list configures a model that fails on the first real turn,
    which is the worst place to find out.

    A rate limit or a cold start is reported as capacity, never as a rejection.
    The free tiers this project is built for look exactly like that when they
    wake up, and failing them would throw away models that work a minute later.
    """
    from ..providers import preflight

    settings = Settings()
    if settings.llm_mock:
        print("Mock mode (CORP_LLM_MOCK=true): no provider to call. Nothing to prove.")
        raise SystemExit(1)

    # `--all` is the console's "Check every model" from a terminal — for anyone
    # over SSH or in a cron job, who does not have the button. Same worker, same
    # accounting, and the same rule: the price is stated before anything runs.
    if getattr(args, "all", False):
        store = open_store()
        est = preflight.estimate()
        print(
            f"This would call {est['total']} model(s) across {len(est['providers'])} provider(s):"
        )
        for name, n in sorted(est["providers"].items(), key=lambda kv: -kv[1]):
            print(f"  {name:<14} {n:>4}")
        if not est["total"]:
            print("Nothing to call. Set a provider key first.")
            raise SystemExit(1)
        if not args.yes:
            # Their keys, their rate limits. A terminal has no confirm dialog,
            # so this is the equivalent — and `--yes` is how a cron job says it
            # already knows.
            print("\nEach one is a real generation on your own account.")
            print("Re-run with --yes to go ahead, or --provider <name> for one provider.")
            return
        result = preflight.sweep(store, limit=args.limit or 0, timeout=args.timeout)
        print(f"\n{result['probed']} called: {result['counts']}")
        print("Remembered, so recommended routing and the model picker can use it.")
        return

    # `--provider` sweeps a whole catalogue instead of the configured tiers.
    # This is where the gap is widest: on NVIDIA, 8 of 14 sampled entries
    # answered 404 for a real key, out of 102 advertised.
    if getattr(args, "provider", ""):
        store = open_store()
        probes = preflight.probe_catalogue(args.provider, limit=args.limit, timeout=args.timeout)
        if not probes:
            print(f"{args.provider} did not answer with a catalogue, so there was nothing to try.")
            raise SystemExit(1)
        preflight.remember(store, probes)
        usable = [p for p in probes if p.state == preflight.USABLE]
        blocked = [p for p in probes if p.state == preflight.BLOCKED]
        for p in probes:
            print(f"  [{p.state:<8}] {p.model}")
            if p.state != preflight.USABLE:
                print(f"             {p.detail[:110]}")
        print(
            f"\n{len(usable)} usable, {len(blocked)} not callable with this key, "
            f"{len(probes) - len(usable) - len(blocked)} cold or unclear, of {len(probes)} tried."
        )
        if not any(p.status for p in probes):
            # Nothing was actually called — no key, or the endpoint never
            # answered. Saying "remembered" here would claim knowledge that does
            # not exist, which is the failure this whole command exists to end.
            print("Nothing was called, so nothing was learned. Set the key first.")
            raise SystemExit(1)
        print(f"Remembered for {args.provider}, so the console can offer the ones that answered.")
        return

    # Refresh what the providers say a model *is*, alongside measuring what it
    # does. This is the one command that already goes to the network on purpose,
    # so it is the right place — routing itself never fetches.
    from ..providers import modelinfo

    catalogue = modelinfo.refresh(open_store())
    if catalogue:
        print(f"Model catalogue: {len(catalogue)} models described by their providers.")

    plan = preflight.targets(settings)
    if not plan:
        print("No tier points at an API provider, so there is nothing to call.")
        raise SystemExit(1)

    print(f"Calling {len(plan)} model(s) for {preflight.MAX_TOKENS} tokens each…")
    report = preflight.run(settings, timeout=args.timeout)
    store = open_store()
    preflight.save(store, report)

    if getattr(args, "json", False):
        print(json.dumps(report.as_dict(), indent=2, ensure_ascii=False))
    else:
        mark = {
            preflight.USABLE: "usable ",
            preflight.BLOCKED: "BLOCKED",
            preflight.CAPACITY: "cold   ",
            preflight.UNKNOWN: "unknown",
        }
        for p in report.probes:
            print(f"  [{mark[p.state]}] {p.tier:<8} {p.provider}:{p.model}")
            print(f"              {p.detail}")
    # Availability answered; now what it is like to use. Only on the handful of
    # models a tier might actually be routed to — several larger calls each, so
    # it is not something to run across a 365-model catalogue.
    usable = [p for p in report.probes if p.state == preflight.USABLE]
    if usable and not getattr(args, "quick", False):
        print(f"\nMeasuring {len(usable)} model(s), {preflight.MEASURE_SAMPLES} samples each…")
        # The catalogue's claim decides whether the picture is worth sending: a
        # model that never said it takes images has nothing to be caught out on,
        # and testing the ones that do say it is where the lie lives.
        catalogue = modelinfo.cached(store)
        for p in usable:
            claims_vision = bool(modelinfo.describe(p.model, catalogue)["vision_declared"])
            m = preflight.measure(p.provider, p.model, timeout=args.timeout, vision=claims_vision)
            preflight.save_measurement(store, m)
            schema = "JSON ok" if m.json_ok else "CANNOT return JSON"
            # Said only when it was asked. "not asked" and "cannot see" are
            # different answers and the line must not merge them.
            if m.vision_ok is True:
                sight = " · reads images"
            elif m.vision_ok is False:
                sight = " · CLAIMS images and cannot read one"
            else:
                sight = ""
            print(
                f"  {p.provider}:{p.model}\n"
                f"     {m.ms} ms median · {m.tok_s} tok/s · {schema} · "
                f"{m.reliability:.0%} of {m.samples} samples{sight}"
            )
    if report.blocking:
        print(
            f"\n{len(report.blocking)} configured model(s) cannot be called with this key. "
            "Pick another in the console (Providers), or run recommended routing."
        )
        raise SystemExit(1)
    if report.transient:
        print(
            f"\n{len(report.transient)} was rate-limited or still waking up. That is capacity, "
            "not a verdict — run this again in a minute to prove it."
        )


def cmd_bench(args) -> None:
    """Measure what this machine can actually run locally.

    One real generation, timed by Ollama. It costs a few seconds — the load
    alone was 6.9s on the machine this was written for — which is why it lives
    behind a command instead of running wherever the answer is wanted.
    """
    from ..providers import hardware

    settings = Settings()
    store = open_store()
    models = hardware.installed_models()
    if not models:
        print("No local model installed, or Ollama is not reachable. Nothing to measure.")
        raise SystemExit(1)
    # Measure the model that would actually be used, not the smallest one:
    # a benchmark of something the company will never run answers nothing.
    from ..config.provider_table import split_target

    want = hardware.best_local_model(models, prefer=split_target(settings.trivial_model)[1])
    spec = hardware.specs()
    result = hardware.measure(want or models[0]["name"])
    if not result["ok"]:
        print(result["detail"])
        raise SystemExit(1)
    hardware.profile_save(store, spec, result)
    choice, why = hardware.recommended_local(store, settings, models)
    if args.json:
        # The verdict, not only the numbers: a script that has to re-derive
        # "is this fast enough" from tokens_per_second will derive it
        # differently from the router, and then the two disagree.
        print(json.dumps({**spec, **result, "local_model": choice, "reason": why}, indent=2))
        return
    ram = f"{spec['ram_total'] / 1e9:.1f} GB" if spec["ram_total"] else "unknown"
    free = f"{spec['ram_available'] / 1e9:.1f} GB free" if spec["ram_available"] else "free unknown"
    print(f"machine: {spec['cores'] or '?'} cores, {ram} ({free})")
    print(
        f"{result['model']}: {result['tokens_per_second']} tokens/s "
        f"on the {result['placement'].upper()}, {result['load_seconds']}s to load"
    )
    choice, why = hardware.recommended_local(store, settings)
    print(f"\nlocal inference: {why}")
    if not choice:
        print("The trivial tier will go to a free provider instead.")


def cmd_claude(args) -> None:
    """Turn on the Claude subscription path, or test it.

    The console has had a one-press card for this since the beginning, but it
    lives in the Providers tab behind fourteen other providers, and an operator
    who drives corparius from a terminal never sees it. Four settings have to
    agree — mock off, cloud on, Claude Code on, and the tiers pointed at
    `claudecode:` — and that hidden conjunction is most of why this was hard to
    turn on. It is one command now, and literally the same plan the console
    applies — same connected providers, same measured local verdict.
    """
    from ..providers import claudecli

    if getattr(args, "install", False) and not claudecli.installed():
        print(f"installing the Claude Code CLI: {claudecli.INSTALL_CMD}")
        print("this takes a minute...")
        done = claudecli.install()
        print(done["detail"])
        if not done["ok"]:
            raise SystemExit(1)
    result = claudecli.check()
    print(result["detail"])
    if args.check:
        return
    if not result["ok"]:
        print("\nnothing changed; fix the above, then run this again")
        raise SystemExit(1)
    # The same two inputs the console passes, or the two paths write different
    # plans from the same decision. This called plan() with no arguments, which
    # reads as "nothing free is connected" and puts every tier on the
    # subscription — the expensive default plan()'s own docstring warns about,
    # and it ignored --all-tiers into the bargain.
    from ..providers.hardware import recommended_local
    from ..providers.llm import connected_providers

    store = open_store()
    local_trivial, _why = recommended_local(store, Settings())
    from ..providers import modelinfo, preflight

    plan = claudecli.plan(
        connected_providers(),
        local_trivial,
        all_tiers=args.all_tiers,
        # What a preflight proved, so this never writes a tier the key
        # cannot call. Empty until one has been run.
        proven=preflight.proven_map(store),
        catalogue=modelinfo.cached(store),
        scores=modelinfo.operator_scores(),
    )
    for key, value in plan.items():
        store.set_setting(key, value)
    every = all(v.startswith("claudecode:") for k, v in plan.items() if k.endswith("_MODEL"))
    print(
        "\nClaude Code is now serving every tier:"
        if every
        else "\nClaude Code now serves the hard tier; free providers keep the rest:"
    )
    for key, value in plan.items():
        print(f"  {key}={value}")
    print("\nNo API key, no credits: calls go through your subscription login.")


def register(sub) -> None:
    sp = sub.add_parser("bench", help="measure what this machine can run locally")
    sp.add_argument("--json", action="store_true", help="machine-readable output")
    sp.set_defaults(fn=cmd_bench)

    sp = sub.add_parser(
        "preflight", help="prove which configured models this account can really call"
    )
    sp.add_argument("--json", action="store_true", help="machine-readable output")
    sp.add_argument("--timeout", type=int, default=25, help="seconds to wait per model")
    sp.add_argument(
        "--provider", default="", help="sweep this provider's whole catalogue instead of the tiers"
    )
    sp.add_argument(
        "--limit",
        type=int,
        default=20,
        help="with --provider, how many models to call (0 = all; each one is a real call)",
    )
    sp.add_argument(
        "--all", action="store_true", help="sweep every configured provider's whole catalogue"
    )
    sp.add_argument("--yes", action="store_true", help="with --all, skip the confirmation")
    sp.add_argument(
        "--quick", action="store_true", help="availability only; skip the performance samples"
    )
    sp.set_defaults(fn=cmd_preflight)

    sp = sub.add_parser("claude", help="use your Claude subscription, no API key")
    sp.add_argument(
        "--check", action="store_true", help="test the CLI login without changing any setting"
    )
    sp.add_argument(
        "--install",
        action="store_true",
        help="install the Claude Code CLI first if it is missing (npm, global)",
    )
    sp.add_argument(
        "--all-tiers",
        action="store_true",
        help="put every tier on the subscription, instead of only the hard one",
    )
    sp.set_defaults(fn=cmd_claude)

    sp = sub.add_parser("mail", help="prove the mail account by sending and reading one message")
    sp.add_argument("--to", default="", help="where to send the test; defaults to the account")
    sp.add_argument("--steps", action="store_true", help="what is left to set up, per provider")
    sp.add_argument("--lang", default="en")
    sp.set_defaults(fn=cmd_mail)
