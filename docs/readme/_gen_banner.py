"""Generate the README hero banners in the console's own visual language:
blue-tinted dark surface, a masked dot-field, the mark on a soft halo, a warm
human-gate accent used once, and a right-aligned pulse of stats — the same
composition as the Overview hero. Dark and light stay in lockstep from one source.

**The mark is drawn here, not embedded.** It was a 213×136 PNG in `_logo.b64`, scaled up to 222
wide — so the first image on the README was an upsampled raster whose baked-in wordmark rendered as
a few illegible pixels. A blind review called it "a low-res raster sprite … the first pixel a
stranger sees and it says dev placeholder". `web/src/Mark.svelte` was redrawn as paths for the
console and this is the same geometry, from the same four fills, so the banner and the running
product cannot drift apart the way they had.
"""

import pathlib

# The mark, at the console's own coordinates: one parent, three reports, wired. The four fills are
# literal here for the reason `Mark.svelte` gives — a brand mark is not a theme — and their lightness
# spread is 0.12 rather than the 0.256 that made four unrelated primaries read as clip-art.
MARK_VIEWBOX = 40, 32


# The drawn extent, which is not the viewBox: the shapes span 1.4-38.6 across and 1.4-30.6 down, so
# centring on 40x32 puts the mark low and left of where it looks centred. Measured rather than
# eyeballed, because the first placement inherited the raster's box and sat 42px below the halo.
INK_X, INK_Y = (1.4 + 38.6) / 2, (1.4 + 30.6) / 2


def mark(cx, cy, scale, wire):
    """The org chart, centred on (cx, cy). `wire` is the stroke colour, which differs per theme."""
    x, y = cx - INK_X * scale, cy - INK_Y * scale
    boxes = "".join(
        f'<rect x="{bx}" y="{by}" width="{bw}" height="{bh}" rx="2.6" fill="{fill}"/>'
        for bx, by, bw, bh, fill in (
            (12.4, 1.4, 15.2, 9.4, "#70bf5c"),
            (1.4, 19.6, 10, 11, "#e1c333"),
            (15, 19.6, 10, 11, "#fc8c44"),
            (28.6, 19.6, 10, 11, "#4aa3f7"),
        )
    )
    return (
        f'<g transform="translate({x},{y}) scale({scale})">'
        f'<path d="M20 11.5v4.5M6.4 16h27.2M6.4 16v3.4M20 16v3.4M33.6 16v3.4" '
        f'stroke="{wire}" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" '
        f'opacity="0.5" fill="none"/>'
        f'<g stroke="{wire}" stroke-width="0.9" stroke-opacity="0.22" paint-order="stroke fill">'
        f"{boxes}</g></g>"
    )


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
    haloop="0.30",
    dotop="0.55",
)


def svg(p):
    # `ink` is gone with the raster it existed for: the PNG logo was too light against a white
    # banner, so the light theme ran it through a darkening filter. The drawn mark needs nothing —
    # its fills were chosen against both headers and measure 1.8-2.6:1 on white, 6.0-8.8:1 on the
    # dark surface. A filter kept "just in case" would be the banner quietly disagreeing with the
    # console about what the brand colour is.
    ink = ""
    return f'''<svg viewBox="0 0 1200 300" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="corparius: self-hosted autonomous AI micro-companies">
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

  <!-- the mark, floated on a soft halo instead of a chip. 40x32 at scale 5.4 is 216x173, which is
       the space the raster used to occupy, drawn, so it is sharp at any size the README is read at. -->
  <ellipse cx="185" cy="150" rx="150" ry="96" fill="url(#halo)"/>
  {mark(185, 150, 4.9, p["text"])}

  <!-- headline block -->
  <text x="356" y="112" font-family="ui-monospace,'SFMono-Regular',Menlo,Consolas,monospace" font-size="13" letter-spacing="3.5" fill="{p["kicker"]}">SELF-HOSTED · LOCAL-FIRST · AUDITABLE</text>
  <text x="355" y="158" font-family="'Segoe UI',system-ui,-apple-system,sans-serif" font-size="35" font-weight="700" fill="{p["text"]}">Autonomous AI micro-companies</text>
  <text x="355" y="199" font-family="'Segoe UI',system-ui,-apple-system,sans-serif" font-size="35" font-weight="700" fill="{p["text"]}">you run yourself.</text>
  <text x="357" y="235" font-family="'Segoe UI',system-ui,-apple-system,sans-serif" font-size="14.5" fill="{p["muted"]}">A CEO and nine agents pursue one signal, revenue, behind a budget and loop firewall.</text>
  <text x="357" y="257" font-family="'Segoe UI',system-ui,-apple-system,sans-serif" font-size="14.5" fill="{p["muted"]}">Cloud LLMs are opt-in, never required. Ship nothing you cannot audit.</text>

  <!-- the one warm accent: the human gate, echoing the console's rule -->
  <g transform="translate(357,272)">
    <circle cx="6" cy="0" r="4.5" fill="{p["warm"]}"/>
    <text x="20" y="4.5" font-family="ui-monospace,'SFMono-Regular',Menlo,Consolas,monospace" font-size="12.5" letter-spacing="0.4" fill="{p["warm"]}">the human gate is the point: money and prod code wait for you</text>
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
