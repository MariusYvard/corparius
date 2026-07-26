"""Generate the README hero banners in the console's own visual language:
blue-tinted dark surface, a masked dot-field, the halo'd pixel logo, a warm
human-gate accent used once, and a right-aligned pulse of stats — the same
composition as the Overview hero. Dark and light stay in lockstep from one source.
"""

import pathlib

B64 = pathlib.Path("docs/readme/_logo.b64").read_text(encoding="utf-8").strip()

# Palette straight from the console tokens (OKLCH -> sRGB).
DARK = dict(
    bg0="#081A3E",
    bg1="#061232",
    dots="#537CD6",
    text="#EFF4FC",
    muted="#9AA5BB",
    kicker="#8CCBFF",
    accent="#2456D3",
    warm="#EB933B",
    teal="#64B8D2",
    border="#254387",
    warmsoft="#2A1F10",
    dotop="0.20",
    logofx="",
    haloop="0.55",
)
LIGHT = dict(
    bg0="#FFFFFF",
    bg1="#EEF2F9",
    dots="#B7C2D8",
    text="#142752",
    muted="#475572",
    kicker="#2456D3",
    accent="#2456D3",
    warm="#AA5900",
    teal="#2E7D96",
    border="#CAD1DF",
    warmsoft="#F3E9D8",
    logofx='filter="url(#ink)"',
    haloop="0.30",
    dotop="0.55",
)


def svg(p):
    ink = (
        ""
        if p["logofx"] == ""
        else '<filter id="ink"><feComponentTransfer>'
        '<feFuncR type="linear" slope="0.34"/><feFuncG type="linear" slope="0.34"/>'
        '<feFuncB type="linear" slope="0.40"/></feComponentTransfer>'
        '<feColorMatrix type="saturate" values="1.3"/></filter>'
    )
    return f'''<svg viewBox="0 0 1200 300" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="corparius — self-hosted autonomous AI micro-companies">
  <defs>
    <linearGradient id="bg" x1="0" y1="0" x2="0.35" y2="1">
      <stop offset="0" stop-color="{p["bg0"]}"/><stop offset="1" stop-color="{p["bg1"]}"/>
    </linearGradient>
    <radialGradient id="halo" cx="0.5" cy="0.5" r="0.5">
      <stop offset="0" stop-color="{p["halo"] if "halo" in p else "#8CCBFF"}" stop-opacity="{p["haloop"]}"/>
      <stop offset="1" stop-color="#8CCBFF" stop-opacity="0"/>
    </radialGradient>
    <linearGradient id="beam" x1="0" y1="0" x2="1" y2="0">
      <stop offset="0" stop-color="{p["teal"]}" stop-opacity="0"/>
      <stop offset="0.35" stop-color="{p["teal"]}" stop-opacity="0.9"/>
      <stop offset="0.6" stop-color="#8CCBFF" stop-opacity="0.9"/>
      <stop offset="1" stop-color="{p["accent"]}" stop-opacity="0"/>
    </linearGradient>
    <pattern id="dots" width="22" height="22" patternUnits="userSpaceOnUse">
      <circle cx="1.5" cy="1.5" r="1.1" fill="{p["dots"]}"/>
    </pattern>
    <radialGradient id="dmask" cx="0.24" cy="-0.05" r="1.05">
      <stop offset="0.28" stop-color="#fff"/><stop offset="0.72" stop-color="#000"/>
    </radialGradient>
    <mask id="fade"><rect width="1200" height="300" fill="url(#dmask)"/></mask>
    {ink}
  </defs>

  <rect width="1200" height="300" fill="url(#bg)"/>
  <rect width="1200" height="300" fill="url(#dots)" opacity="{p["dotop"]}" mask="url(#fade)"/>
  <rect width="1200" height="2.5" fill="url(#beam)"/>

  <!-- logo, floated on a soft halo instead of a chip -->
  <ellipse cx="185" cy="150" rx="150" ry="96" fill="url(#halo)"/>
  <image x="74" y="80" width="222" height="142" href="data:image/png;base64,{B64}" {p["logofx"]}/>

  <!-- headline block -->
  <text x="356" y="112" font-family="ui-monospace,'SFMono-Regular',Menlo,Consolas,monospace" font-size="13" letter-spacing="3.5" fill="{p["kicker"]}">SELF-HOSTED · LOCAL-FIRST · AUDITABLE</text>
  <text x="355" y="158" font-family="'Segoe UI',system-ui,-apple-system,sans-serif" font-size="35" font-weight="700" fill="{p["text"]}">Autonomous AI micro-companies</text>
  <text x="355" y="199" font-family="'Segoe UI',system-ui,-apple-system,sans-serif" font-size="35" font-weight="700" fill="{p["text"]}">you run yourself.</text>
  <text x="357" y="235" font-family="'Segoe UI',system-ui,-apple-system,sans-serif" font-size="14.5" fill="{p["muted"]}">A CEO and nine agents pursue one signal — revenue — behind a budget and loop firewall.</text>
  <text x="357" y="257" font-family="'Segoe UI',system-ui,-apple-system,sans-serif" font-size="14.5" fill="{p["muted"]}">Cloud LLMs are opt-in, never required. Ship nothing you cannot audit.</text>

  <!-- the one warm accent: the human gate, echoing the console's rule -->
  <g transform="translate(357,272)">
    <circle cx="6" cy="0" r="4.5" fill="{p["warm"]}"/>
    <text x="20" y="4.5" font-family="ui-monospace,'SFMono-Regular',Menlo,Consolas,monospace" font-size="12.5" letter-spacing="0.4" fill="{p["warm"]}">the human gate is the point — money and prod code wait for you</text>
  </g>

  <!-- right-aligned pulse, the way the Overview hero carries its stats -->
  <g font-family="'Segoe UI',system-ui,sans-serif" text-anchor="middle">
    <line x1="1000" y1="122" x2="1000" y2="196" stroke="{p["border"]}" stroke-width="1"/>
    <text x="1058" y="128" font-size="11.5" letter-spacing="0.6" fill="{p["muted"]}">agents</text>
    <text x="1058" y="164" font-size="30" font-weight="700" fill="{p["text"]}">10</text>
    <text x="1150" y="128" font-size="11.5" letter-spacing="0.6" fill="{p["muted"]}">signal</text>
    <text x="1150" y="160" font-size="19" font-weight="700" fill="{p["teal"]}">revenue</text>
    <text x="1104" y="192" font-size="11.5" letter-spacing="0.6" fill="{p["muted"]}">to start</text>
    <text x="1104" y="216" font-size="19" font-weight="700" fill="{p["text"]}">offline · no keys</text>
  </g>
</svg>
'''


DARK["halo"] = "#8CCBFF"
LIGHT["halo"] = "#8CCBFF"
pathlib.Path("docs/banner-dark.svg").write_text(svg(DARK), encoding="utf-8")
pathlib.Path("docs/banner.svg").write_text(svg(LIGHT), encoding="utf-8")
print("wrote docs/banner-dark.svg and docs/banner.svg")
