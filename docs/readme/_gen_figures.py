"""The README's explaining figures, in the console's own language.

`_gen_diagram.py` draws the one-tick pipeline and the divider; this draws the four that replace
tables and walls of prose — the roster, the guards, routing, and the four ways to teach a company.
Same palettes, same card and chip primitives, so the README reads as one surface rather than as a
scrapbook.

Written because the README was 552 lines of prose with three pictures in it, and the things hardest
to hold in a paragraph are exactly the ones a picture is for: ten agents on staggered cadences, three
guards each stopping a different failure, a tier falling through a chain to a local model. Each
figure below replaces text that is now deleted, not text that is now illustrated twice.

Dark and light from one source, so both themes match the interface exactly.
"""

import pathlib

DARK = dict(
    bg0="#081A3E",
    bg1="#061232",
    card="#0A1D48",
    cardln="#254387",
    sunken="#061634",
    dots="#537CD6",
    text="#EFF4FC",
    muted="#9AA5BB",
    kicker="#8CCBFF",
    accent="#2456D3",
    warm="#EB933B",
    warmln="#7A4E1E",
    teal="#64B8D2",
    green="#70BF5C",
    arrow="#537CD6",
    dotop="0.16",
)
LIGHT = dict(
    bg0="#FFFFFF",
    bg1="#EEF2F9",
    card="#FFFFFF",
    cardln="#CAD1DF",
    sunken="#F3F6FB",
    dots="#B7C2D8",
    text="#142752",
    muted="#475572",
    kicker="#2456D3",
    accent="#2456D3",
    warm="#AA5900",
    warmln="#E0C79A",
    teal="#2E7D96",
    green="#3F7A31",
    arrow="#9AA9C6",
    dotop="0.5",
)

SANS = "'Segoe UI',system-ui,-apple-system,sans-serif"
MONO = "ui-monospace,Menlo,Consolas,monospace"


def frame(w, h, p, kicker, label):
    """The surface every figure sits on: the console's gradient, its masked dot field, its kicker."""
    return f'''<svg viewBox="0 0 {w} {h}" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="{label}">
  <defs>
    <linearGradient id="bg" x1="0" y1="0" x2="0.4" y2="1"><stop offset="0" stop-color="{p["bg0"]}"/><stop offset="1" stop-color="{p["bg1"]}"/></linearGradient>
    <pattern id="dots" width="22" height="22" patternUnits="userSpaceOnUse"><circle cx="1.5" cy="1.5" r="1.1" fill="{p["dots"]}"/></pattern>
    <radialGradient id="dm" cx="0.2" cy="-0.05" r="1.05"><stop offset="0.3" stop-color="#fff"/><stop offset="0.75" stop-color="#000"/></radialGradient>
    <mask id="fade"><rect width="{w}" height="{h}" fill="url(#dm)"/></mask>
    <marker id="ah" markerWidth="8" markerHeight="8" refX="6" refY="4" orient="auto"><path d="M1 1 L6 4 L1 7" fill="none" stroke="{p["arrow"]}" stroke-width="1.6"/></marker>
  </defs>
  <rect width="{w}" height="{h}" rx="16" fill="url(#bg)"/>
  <rect width="{w}" height="{h}" fill="url(#dots)" opacity="{p["dotop"]}" mask="url(#fade)"/>
  <text x="36" y="42" font-family="{MONO}" font-size="13" letter-spacing="3" fill="{p["kicker"]}">{kicker}</text>
'''


def card(x, y, w, h, p, ln=None, fill=None, tint=None):
    ln = ln or p["cardln"]
    s = f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="12" fill="{fill or p["card"]}" stroke="{ln}" stroke-width="1.3"/>'
    if tint:
        s += (
            f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="12" fill="{tint}" opacity="0.07"/>'
        )
    return s


def text(x, y, s, p, size=14, weight=400, fill="text", mono=False, anchor="start"):
    family = MONO if mono else SANS
    w = f' font-weight="{weight}"' if weight != 400 else ""
    a = f' text-anchor="{anchor}"' if anchor != "start" else ""
    return (
        f'<text x="{x}" y="{y}" font-family="{family}" font-size="{size}"{w}{a} '
        f'fill="{p[fill]}">{s}</text>'
    )


def chip(x, y, label, p, colour="cardln", ink="muted"):
    w = 12 + len(label) * 7.0
    return (
        f'<rect x="{x}" y="{y}" width="{w:.0f}" height="23" rx="11.5" fill="none" '
        f'stroke="{p[colour]}" stroke-width="1"/>'
        + text(x + w / 2, y + 16, label, p, size=11.5, fill=ink, mono=True, anchor="middle"),
        w,
    )


# --- 1. the roster ----------------------------------------------------------------
#
# Ten rows of a markdown table, which is where a reader's eye goes to die. What the table could not
# say at all is the thing that matters most about the roster: the cadences are **staggered on
# purpose**, so the company does not spend its whole budget in one burst. That is a shape, so it is
# drawn as one — a 24-hour rail with a tick wherever a role actually runs.

ROSTER = [
    ("CEO", "orchestrator · owns the backlog", 12, "warm"),
    ("Social", "drafts and schedules posts", 2, "accent"),
    ("Outreach", "finds targets, sends, tracks replies", 3, "accent"),
    ("Support", "triages the inbox, drafts replies", 3, "accent"),
    ("Ads", "budgets, variants, bids", 6, "accent"),
    ("Finance", "reconciles Stripe, tracks spend", 6, "accent"),
    ("Strategy", "reads KPIs, prices, roadmap", 24, "teal"),
    ("Competitor", "researches, updates profiles", 24, "teal"),
    ("Design", "visual direction, builds the site", 24, "teal"),
    ("Coder", "features, fixes, pull requests", 0, "green"),
]


def roster(p):
    W, ROW = 1200, 46
    top = 108
    H = top + len(ROSTER) * ROW + 40
    s = frame(
        W,
        H,
        p,
        "THE ROSTER · TEN ROLES, STAGGERED",
        "the ten agents and when each runs across a day: the CEO twice a day, social every two "
        "hours, outreach and support every three, ads and finance every six, strategy, competitor "
        "and design daily, and the coder on demand",
    )
    rail_x, rail_w = 470, W - 470 - 60

    # The hour scale, once, above the rail.
    for hour in (0, 6, 12, 18, 24):
        x = rail_x + rail_w * hour / 24
        s += text(x, top - 26, f"{hour:02d}h", p, size=11, fill="muted", mono=True, anchor="middle")
        s += f'<line x1="{x:.1f}" y1="{top - 18}" x2="{x:.1f}" y2="{H - 30}" stroke="{p["cardln"]}" stroke-width="1" opacity="0.45"/>'

    for i, (name, does, every, colour) in enumerate(ROSTER):
        y = top + i * ROW
        s += text(60, y + 22, name, p, size=15, weight=700)
        s += text(172, y + 22, does, p, size=12.5, fill="muted", mono=True)
        # No rail for the role that has no cadence — a hairline with a sentence lying across it
        # reads as a struck-through line, and the one role that is *not* on the clock is exactly
        # the one that must not look cancelled.
        if every == 0:
            s += text(
                rail_x,
                y + 22,
                "on demand, when the CEO files a task",
                p,
                size=12.5,
                fill="muted",
                mono=True,
            )
            continue
        # The rail: a hairline for the day, a mark at each hour the role is due.
        s += f'<line x1="{rail_x}" y1="{y + 17}" x2="{rail_x + rail_w}" y2="{y + 17}" stroke="{p["cardln"]}" stroke-width="1"/>'
        hour = 0
        while hour < 24:
            x = rail_x + rail_w * hour / 24
            s += f'<circle cx="{x:.1f}" cy="{y + 17}" r="4.5" fill="{p[colour]}"/>'
            hour += every
    return s + "</svg>\n"


# --- 2. the guards ----------------------------------------------------------------
#
# Three bullets and a separate section for the gate. They belong in one picture because they are one
# sequence: three automatic guards a turn passes through, and then a human one it stops at.

GUARDS = [
    (
        "TokenBudget",
        "a hard ceiling per session",
        "checked before each call,\nupdated after",
        "accent",
    ),
    (
        "LoopGuard",
        "semantic stutter, and repeats",
        "cosine over the last outputs,\nidentical tool calls counted",
        "accent",
    ),
    (
        "CircuitBreaker",
        "spend velocity",
        "a sustained burst trips\nNORMAL → CONSERVATIVE → SAFE",
        "accent",
    ),
]


def guards(p):
    W, H = 1200, 356
    s = frame(
        W,
        H,
        p,
        "EVERY TURN PASSES THREE GUARDS, THEN STOPS AT YOU",
        "three automatic guards in front of every agent turn (a token budget, a loop guard and a "
        "circuit breaker), and then the human gate, where money and production code wait for the "
        "operator",
    )
    CW, CH, y = 268, 150, 84
    for i, (name, catches, how, colour) in enumerate(GUARDS):
        x = 36 + i * (CW + 22)
        s += card(x, y, CW, CH, p)
        s += text(x + 18, y + 32, name, p, size=16.5, weight=700)
        s += text(x + 18, y + 56, catches, p, size=12.5, fill=colour, mono=True)
        for j, line in enumerate(how.split("\n")):
            s += text(x + 18, y + 84 + j * 19, line, p, size=12.5, fill="muted")
        s += f'<path d="M{x + CW} {y + CH / 2} L{x + CW + 18} {y + CH / 2}" stroke="{p["arrow"]}" stroke-width="1.6" marker-end="url(#ah)"/>'

    # The gate: warm, wider, and the only one with a person in it.
    gx = 36 + 3 * (CW + 22)
    gw = W - gx - 36
    s += card(gx, y, gw, CH, p, ln=p["warm"], tint=p["warm"])
    s += f'<circle cx="{gx + gw - 24}" cy="{y + 24}" r="5" fill="{p["warm"]}"/>'
    s += text(gx + 18, y + 32, "Human gate", p, size=16.5, weight=700)
    s += text(gx + 18, y + 56, "money · production code", p, size=12.5, fill="warm", mono=True)
    s += text(gx + 18, y + 84, "the request waits with what", p, size=12.5, fill="muted")
    s += text(gx + 18, y + 103, "it will do and the values it", p, size=12.5, fill="muted")
    s += text(gx + 18, y + 122, "will run with. A rejection is", p, size=12.5, fill="muted")
    s += text(gx + 18, y + 141, "handed back as a tool error.", p, size=12.5, fill="muted")

    # What it costs when they are absent, said once, in the operator's terms.
    s += f'<rect x="36" y="{y + CH + 26}" width="{W - 72}" height="52" rx="12" fill="{p["sunken"]}" stroke="{p["cardln"]}" stroke-width="1.3"/>'
    s += text(
        56,
        y + CH + 57,
        "An autonomous agent alone with an API key and a card is a runaway-cost incident waiting to happen. These are what make it not one.",
        p,
        size=13.5,
        fill="muted",
    )
    return s + "</svg>\n"


# --- 3. routing -------------------------------------------------------------------
#
# A fourteen-provider table, which is reference material and belongs in `docs/llm-providers.md`
# where it already lives. What the README has to show is the *shape*: three tiers, each pinned to a
# target, and a chain that always ends somewhere that needs no network.

TIERS = [
    ("CORP_TRIVIAL_MODEL", "trivial", "local:gemma4:e4b", "green"),
    ("CORP_NORMAL_MODEL", "normal", "groq:llama-3.3-70b-versatile", "accent"),
    ("CORP_HARD_MODEL", "hard", "openrouter:deepseek/deepseek-r1-0528:free", "teal"),
]


def routing(p):
    W, H = 1200, 372
    s = frame(
        W,
        H,
        p,
        "ROUTING · THREE TIERS, ONE CHAIN, ALWAYS A WAY HOME",
        "the three difficulty tiers each map to a provider target, and a failed call walks the "
        "fallback chain in order until it reaches the local model, which needs no network",
    )
    y = 82
    for i, (env, tier, target, colour) in enumerate(TIERS):
        ty = y + i * 62
        s += card(36, ty, 470, 50, p)
        s += text(54, ty + 31, env, p, size=13, fill="muted", mono=True)
        c, w = chip(370, ty + 13, tier, p, colour=colour, ink=colour)
        s += c
        s += f'<path d="M506 {ty + 25} L560 {ty + 25}" stroke="{p["arrow"]}" stroke-width="1.6" marker-end="url(#ah)"/>'
        s += card(572, ty, W - 572 - 36, 50, p, ln=p[colour])
        s += text(590, ty + 31, target, p, size=13.5, mono=True)

    # The chain, as a sunken strip: the thing an operator needs to believe is that it ends locally.
    cy = y + 3 * 62 + 14
    s += f'<rect x="36" y="{cy}" width="{W - 72}" height="86" rx="12" fill="{p["sunken"]}" stroke="{p["cardln"]}" stroke-width="1.3"/>'
    s += text(56, cy + 28, "When a remote call fails", p, size=14, weight=700)
    s += text(
        56,
        cy + 50,
        "rate limit, outage, a model that cannot answer",
        p,
        size=12.5,
        fill="muted",
        mono=True,
    )
    steps = [
        ("groq", "accent"),
        ("cerebras", "accent"),
        ("mistral", "accent"),
        ("local · offline", "green"),
    ]
    sx = 560
    for i, (label, colour) in enumerate(steps):
        c, w = chip(sx, cy + 32, label, p, colour=colour, ink=colour)
        s += c
        sx += w
        if i < len(steps) - 1:
            s += f'<path d="M{sx + 6} {cy + 43} L{sx + 26} {cy + 43}" stroke="{p["arrow"]}" stroke-width="1.4" marker-end="url(#ah)"/>'
            sx += 34
    s += text(
        56,
        cy + 74,
        "A provider that refuses goes to the end of the chain rather than being dropped, and comes back once it is rested.",
        p,
        size=12.5,
        fill="muted",
    )
    return s + "</svg>\n"


# --- 4. what a company can be taught ----------------------------------------------
#
# Four sections of the README each opened by explaining how it differed from the other three. One
# picture says it: code, prose, files, and a thing the company runs.

WAYS = [
    (
        "Plugins",
        "code",
        "providers, tools, templates,\nwithout touching the core",
        "plugins/registry.json",
        "accent",
    ),
    (
        "Skills",
        "prose",
        "the objection your market raises,\nthe price you never discount below",
        "SKILL.md",
        "teal",
    ),
    (
        "Documents",
        "files",
        "the deck, the spec, the price list:\nread with the standard library",
        "documents/",
        "green",
    ),
    (
        "Apps",
        "its own",
        "a FAQ on the sales site, a form\nthat understands what a visitor wrote",
        "apps/*.yaml",
        "warm",
    ),
]


def teaching(p):
    W, H = 1200, 300
    s = frame(
        W,
        H,
        p,
        "FOUR WAYS TO TEACH A COMPANY",
        "plugins add code, skills add prose, documents are the files it already has, and apps are "
        "what it runs for its own visitors",
    )
    # (1200 - 36 left - 36 right - 3 gaps of 20) / 4. Computed rather than eyeballed: 276 put the
    # fourth card's right edge exactly on the canvas edge, with no margin at all on one side only.
    CW, y, CH = 267, 84, 172
    for i, (name, kind, what, where, colour) in enumerate(WAYS):
        x = 36 + i * (CW + 20)
        # Every card takes the neutral border. A warm border means "this is waiting for you" in the
        # console, and it is the one signal in the whole palette that must not be spent on emphasis:
        # apps are not the human gate. The chip carries the colour instead.
        s += card(x, y, CW, CH, p)
        s += text(x + 18, y + 34, name, p, size=17, weight=700)
        c, w = chip(x + 18, y + 48, kind, p, colour=colour, ink=colour)
        s += c
        for j, line in enumerate(what.split("\n")):
            s += text(x + 18, y + 100 + j * 19, line, p, size=12.5, fill="muted")
        s += text(x + 18, y + 152, where, p, size=12, fill=colour, mono=True)
    return s + "</svg>\n"


FIGURES = {"roster": roster, "guards": guards, "routing": routing, "teaching": teaching}

if __name__ == "__main__":
    out = pathlib.Path("docs/readme")
    out.mkdir(exist_ok=True)
    for name, fn in FIGURES.items():
        (out / f"{name}-dark.svg").write_text(fn(DARK), encoding="utf-8")
        (out / f"{name}.svg").write_text(fn(LIGHT), encoding="utf-8")
    print("wrote", ", ".join(FIGURES))
