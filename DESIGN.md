# corparius, design system

## Theme

Dark by default (operator checks in at night next to a terminal), light theme available, persisted client-side. Never pure black or pure white; every neutral is tinted toward the accent hue (oklch hue 155).

## Color, restrained strategy

Source palette (Adobe Color, owner-provided): #102857 night blue, #215876 petrol, #F2F1DF ivory, #BF9B6F sand, #D97F30 amber.

Dark:  bg oklch(0.21 0.04 262) · surface oklch(0.255 0.055 262) · raised oklch(0.31 0.06 255) · border oklch(0.40 0.055 250) · border-ui oklch(0.55 0.045 245) · text oklch(0.95 0.022 106) (ivory) · muted oklch(0.74 0.035 240)
Light: bg oklch(0.955 0.022 106) (#F2F1DF) · surface oklch(0.978 0.014 106) · raised oklch(0.925 0.026 100) · border oklch(0.82 0.035 95) · border-ui oklch(0.60 0.045 245) · text oklch(0.283 0.083 264) (#102857) · muted oklch(0.45 0.055 250)

Accent (amber #D97F30): dark oklch(0.70 0.13 59), light oklch(0.50 0.12 59). On-accent ink: night blue on dark, ivory on light.
Semantic: ok = petrol (#215876 family) · waiting = sand (#BF9B6F family) · danger = functional red (off-palette by necessity). Accent is for primary actions, selection, progress. border-ui carries the 3:1 non-text contrast for interactive controls; card borders stay quieter by design.

## Typography

System stack: -apple-system, "Segoe UI", system-ui, sans-serif. Mono for data (ids, counts, tokens, log lines): ui-monospace, "Cascadia Mono", monospace.
Scale (1.125): 12 / 13 / 15 / 17 / 19 / 22. Body 15. Weights 400 and 600 only.

## Spacing and layout

4px base. Comfortable density: card padding 20, section gaps 24-32, table rows 10 vertical. Max content width 1200, centered. Two-column grid on desktop (main 2fr, aside 1fr), stacked below 900px.

## Components

Cards: surface bg, 1px border, radius 10, padding 24, no shadow in dark (border carries elevation), soft shadow in light. Buttons: primary (accent bg, ink text), quiet (transparent, border), danger-quiet. Radius 8. Badges: tinted bg at 12-18% alpha + colored text, radius 999. Tabs: underline indicator, no pills. Inputs: raised bg, border, focus ring 2px accent at 40%.

## Motion

150-200ms, cubic-bezier(0.22, 1, 0.36, 1) (ease-out-quint), opacity and transform only. State changes only; no page-load choreography. prefers-reduced-motion collapses all to none.

## Bans (project-level)

No gradients, no glassmorphism, no side-stripe borders, no modals (inline confirmation), no emoji in UI; icons are the owner's pixel-art set on ivory chips (image-rendering: pixelated), inline SVG (1.5px stroke, currentColor) for the rare glyph the set lacks, no spinners mid-content (skeletons).
