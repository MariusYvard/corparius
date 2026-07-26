"""The 'how it works' pipeline as a bento of cards in the console's language,
and a slim divider that echoes the logo's org-tree. Dark and light from one
source, so both themes match the interface exactly.
"""

import pathlib

DARK = dict(
    bg0="#081A3E",
    bg1="#061232",
    card="#0A1D48",
    cardln="#254387",
    dots="#537CD6",
    text="#EFF4FC",
    muted="#9AA5BB",
    kicker="#8CCBFF",
    accent="#2456D3",
    warm="#EB933B",
    warmln="#7A4E1E",
    warmfill="#1C1608",
    teal="#64B8D2",
    arrow="#537CD6",
    dotop="0.16",
)
LIGHT = dict(
    bg0="#FFFFFF",
    bg1="#EEF2F9",
    card="#FFFFFF",
    cardln="#CAD1DF",
    dots="#B7C2D8",
    text="#142752",
    muted="#475572",
    kicker="#2456D3",
    accent="#2456D3",
    warm="#AA5900",
    warmln="#E0C79A",
    warmfill="#FBF3E4",
    teal="#2E7D96",
    arrow="#9AA9C6",
    dotop="0.5",
)


def card(x, y, w, h, p, title, sub, accent=None, dashed=False):
    ln = accent or p["cardln"]
    dash = ' stroke-dasharray="5 4"' if dashed else ""
    g = f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="12" fill="{p["card"]}" stroke="{ln}" stroke-width="1.3"{dash}/>'
    g += f'<text x="{x + 18}" y="{y + 30}" font-family="\'Segoe UI\',system-ui,sans-serif" font-size="16.5" font-weight="700" fill="{p["text"]}">{title}</text>'
    g += f'<text x="{x + 18}" y="{y + 54}" font-family="ui-monospace,Menlo,Consolas,monospace" font-size="12.5" fill="{p["muted"]}">{sub}</text>'
    return g


def chip(x, y, label, p):
    w = 10 + len(label) * 7.4
    return (
        f'<rect x="{x}" y="{y}" width="{w:.0f}" height="24" rx="12" fill="none" stroke="{p["cardln"]}" stroke-width="1"/>'
        f'<text x="{x + w / 2:.0f}" y="{y + 16}" text-anchor="middle" font-family="ui-monospace,Menlo,Consolas,monospace" font-size="11.5" fill="{p["muted"]}">{label}</text>'
    ), w


def arrow(x1, y1, x2, y2, p):
    return f'<path d="M{x1} {y1} L{x2} {y2}" stroke="{p["arrow"]}" stroke-width="1.6" fill="none" marker-end="url(#ah)"/>'


def diagram(p):
    W, H = 1200, 430
    CW, CH = 344, 96
    xs = [36, 428, 820]
    y1, y2 = 78, 214
    s = f'''<svg viewBox="0 0 {W} {H}" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="how corparius works: company config to scheduler to agent turn to guarded tool calls to the human gate to the store to the interfaces">
  <defs>
    <linearGradient id="bg" x1="0" y1="0" x2="0.4" y2="1"><stop offset="0" stop-color="{p["bg0"]}"/><stop offset="1" stop-color="{p["bg1"]}"/></linearGradient>
    <pattern id="dots" width="22" height="22" patternUnits="userSpaceOnUse"><circle cx="1.5" cy="1.5" r="1.1" fill="{p["dots"]}"/></pattern>
    <radialGradient id="dm" cx="0.2" cy="-0.05" r="1.05"><stop offset="0.3" stop-color="#fff"/><stop offset="0.75" stop-color="#000"/></radialGradient>
    <mask id="fade"><rect width="{W}" height="{H}" fill="url(#dm)"/></mask>
    <marker id="ah" markerWidth="8" markerHeight="8" refX="6" refY="4" orient="auto"><path d="M1 1 L6 4 L1 7" fill="none" stroke="{p["arrow"]}" stroke-width="1.6"/></marker>
  </defs>
  <rect width="{W}" height="{H}" rx="16" fill="url(#bg)"/>
  <rect width="{W}" height="{H}" fill="url(#dots)" opacity="{p["dotop"]}" mask="url(#fade)"/>
  <text x="36" y="42" font-family="ui-monospace,Menlo,Consolas,monospace" font-size="13" letter-spacing="3" fill="{p["kicker"]}">HOW IT WORKS · ONE TICK</text>
'''
    # row 1
    s += card(xs[0], y1, CW, CH, p, "company.yaml", "a business in plain language", dashed=True)
    s += card(xs[1], y1, CW, CH, p, "Scheduler", "picks the agents due this tick")
    s += card(xs[2], y1, CW, CH, p, "Agent turn", "HybridRouter · local, then cloud")
    # row 2
    s += card(xs[0], y2, CW, CH, p, "Tool calls", "guarded on every turn")
    s += card(
        xs[1], y2, CW, CH, p, "Human gate", "money / prod code wait for you", accent=p["warm"]
    )
    # warm fill tint on the gate card
    s += f'<rect x="{xs[1]}" y="{y2}" width="{CW}" height="{CH}" rx="12" fill="{p["warm"]}" opacity="0.07"/>'
    s += f'<circle cx="{xs[1] + CW - 22}" cy="{y2 + 22}" r="5" fill="{p["warm"]}"/>'
    s += card(xs[2], y2, CW, CH, p, "Store", "SQLite · actions, usage, approvals, KPIs")
    # guard chips under Tool calls
    cx = xs[0] + 16
    for lab in ["TokenBudget", "LoopGuard", "CircuitBreaker"]:
        c, w = chip(cx, y2 + 60, lab, p)
        s += c
        cx += w + 8
    # arrows: within row1
    s += arrow(xs[0] + CW, y1 + CH / 2, xs[1] - 4, y1 + CH / 2, p)
    s += arrow(xs[1] + CW, y1 + CH / 2, xs[2] - 4, y1 + CH / 2, p)
    # elbow from Agent turn (row1 right) down to Tool calls (row2 left)
    s += f'<path d="M{xs[2] + CW / 2} {y1 + CH} L{xs[2] + CW / 2} {y1 + CH + 20} Q{xs[2] + CW / 2} {y1 + CH + 30} {xs[2] + CW / 2 - 10} {y1 + CH + 30} L{xs[0] + CW / 2 + 10} {y1 + CH + 30} Q{xs[0] + CW / 2} {y1 + CH + 30} {xs[0] + CW / 2} {y1 + CH + 40} L{xs[0] + CW / 2} {y2 - 4}" stroke="{p["arrow"]}" stroke-width="1.6" fill="none" marker-end="url(#ah)"/>'
    # row2 arrows
    s += arrow(xs[0] + CW, y2 + CH / 2, xs[1] - 4, y2 + CH / 2, p)
    s += arrow(xs[1] + CW, y2 + CH / 2, xs[2] - 4, y2 + CH / 2, p)
    # store -> interfaces
    yb = 360
    s += f'<path d="M{xs[2] + CW / 2} {y2 + CH} L{xs[2] + CW / 2} {yb - 4}" stroke="{p["arrow"]}" stroke-width="1.6" fill="none" marker-end="url(#ah)"/>'
    # interfaces bar
    s += f'<rect x="36" y="{yb}" width="{W - 72}" height="46" rx="12" fill="{p["card"]}" stroke="{p["cardln"]}" stroke-width="1.3"/>'
    s += f'<text x="54" y="{yb + 29}" font-family="\'Segoe UI\',system-ui,sans-serif" font-size="14.5" font-weight="700" fill="{p["text"]}">Interfaces</text>'
    for i, lab in enumerate(["CLI", "operator console", "MCP server"]):
        lx = 190 + i * 210
        s += f'<circle cx="{lx}" cy="{yb + 23}" r="3.5" fill="{p["teal"]}"/>'
        s += f'<text x="{lx + 12}" y="{yb + 28}" font-family="ui-monospace,Menlo,Consolas,monospace" font-size="13" fill="{p["muted"]}">{lab}</text>'
    s += "</svg>\n"
    return s


def divider(p):
    # a slim rule that recalls the logo's org-tree: one parent node, three children
    W = 1200
    accent, warm, teal = p["accent"], p["warm"], p["teal"]
    return f'''<svg viewBox="0 0 {W} 30" xmlns="http://www.w3.org/2000/svg" role="presentation">
  <defs><linearGradient id="r" x1="0" y1="0" x2="1" y2="0">
    <stop offset="0" stop-color="{p["cardln"]}" stop-opacity="0"/>
    <stop offset="0.5" stop-color="{p["cardln"]}" stop-opacity="0.9"/>
    <stop offset="1" stop-color="{p["cardln"]}" stop-opacity="0"/></linearGradient></defs>
  <line x1="0" y1="15" x2="{W / 2 - 70}" y2="15" stroke="url(#r)" stroke-width="1"/>
  <line x1="{W / 2 + 70}" y1="15" x2="{W}" y2="15" stroke="url(#r)" stroke-width="1"/>
  <g>
    <line x1="{W / 2}" y1="8" x2="{W / 2}" y2="14" stroke="{p["muted"]}" stroke-width="1"/>
    <line x1="{W / 2 - 24}" y1="14" x2="{W / 2 + 24}" y2="14" stroke="{p["muted"]}" stroke-width="1"/>
    <line x1="{W / 2 - 24}" y1="14" x2="{W / 2 - 24}" y2="19" stroke="{p["muted"]}" stroke-width="1"/>
    <line x1="{W / 2 + 24}" y1="14" x2="{W / 2 + 24}" y2="19" stroke="{p["muted"]}" stroke-width="1"/>
    <rect x="{W / 2 - 3}" y="4" width="6" height="6" rx="1.5" fill="{teal}"/>
    <rect x="{W / 2 - 27}" y="19" width="6" height="6" rx="1.5" fill="{accent}"/>
    <rect x="{W / 2 - 3}" y="19" width="6" height="6" rx="1.5" fill="{warm}"/>
    <rect x="{W / 2 + 21}" y="19" width="6" height="6" rx="1.5" fill="{accent}"/>
  </g>
</svg>
'''


pathlib.Path("docs/readme").mkdir(exist_ok=True)
pathlib.Path("docs/readme/pipeline-dark.svg").write_text(diagram(DARK), encoding="utf-8")
pathlib.Path("docs/readme/pipeline.svg").write_text(diagram(LIGHT), encoding="utf-8")
pathlib.Path("docs/readme/rule-dark.svg").write_text(divider(DARK), encoding="utf-8")
pathlib.Path("docs/readme/rule.svg").write_text(divider(LIGHT), encoding="utf-8")
print("wrote pipeline + rule (dark/light)")
