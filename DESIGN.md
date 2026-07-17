# corparius, design system

## Theme

Dark by default (operator checks in at night next to a terminal), light theme available, persisted client-side. Never pure black or pure white; every neutral is tinted toward the accent hue (oklch hue 155).

## Color, restrained strategy

Source palette (Adobe Color, owner-provided): #102857 night blue, #215876 petrol, #F2F1DF ivory, #BF9B6F sand, #D97F30 amber.
Structural blue ramp (Adobe Color, owner-provided): #002FA7, #263F7F, #4C7EFF, #0039CC, #0047FF — all hue ~264, the hue the console already used at a third of the chroma. They are structure, never semantics: a console painted entirely in one hue cannot show what waits on you.

Dark:  bg oklch(0.195 0.055 264) · surface oklch(0.245 0.075 264) · raised oklch(0.31 0.095 264) · border oklch(0.385 0.113 265) (#263F7F) · border-ui oklch(0.58 0.13 265) · select oklch(0.628 0.19 265) (#4C7EFF) · text oklch(0.95 0.022 106) (ivory) · muted oklch(0.74 0.035 240)
Light: bg oklch(0.955 0.022 106) (#F2F1DF) · surface oklch(0.978 0.014 106) · raised oklch(0.925 0.026 100) · border oklch(0.82 0.035 95) · border-ui oklch(0.385 0.113 265) · select oklch(0.435 0.21 263) (#0039CC) · text oklch(0.283 0.083 264) (#102857) · muted oklch(0.45 0.055 250)

Measured, not guessed. On dark: ivory 15.9:1 on bg, muted 8.0:1, amber 6.6:1, sand 8.2:1; border-ui 3.8:1 on surface and 3.1:1 on raised (L=0.58 is the floor that clears 3:1 on both). #4C7EFF and #0039CC sit on the sRGB boundary, so their chroma is pulled a hair under the source hex to survive rounding.

Accent (amber #D97F30): dark oklch(0.70 0.13 59), light oklch(0.50 0.12 59). On-accent ink: night blue on dark, ivory on light.

Four named roles. The palette has five colors; using two of them wasted the other three, and
repeating amber on every button spent its authority. Amber must stay rare to stay loud.

| Role | Color | Carries |
| --- | --- | --- |
| **Structure** | blue ramp (~hue 264) | Background, surfaces, borders. Depth, never meaning. |
| **Selection** | #4C7EFF dark, #0039CC light | Focus rings, the active tab, a toggle that is on, links. What is picked, not what to do. |
| **Action** | amber | The one primary action in view. If two things are amber, one is wrong. |
| **Health** | petrol (#215876) | Progress, spend, throughput, anything running as intended. |
| **Waiting** | sand (#BF9B6F) | The human gate. Anything stopped, waiting on the operator. |
| **Danger** | functional red | Refusal and loss. Off-palette by necessity. |

Separating Selection from Action is what buys amber its scarcity: a focus ring, an active tab and a live toggle are all things the interface points at, not things the operator should do next. With those in blue, amber is left on the primary button and nowhere else.

Sand is the console's second voice: PRODUCT.md makes the human gate the point, so what waits
on you reads sand before you read a word. Petrol is the resting state of a company that works.
border-ui carries the 3:1 non-text contrast for interactive controls; card borders stay quieter
by design.

## Typography

System stack: -apple-system, "Segoe UI", system-ui, sans-serif. Mono for data (ids, counts, tokens, log lines): ui-monospace, "Cascadia Mono", monospace.
Scale (1.125): 12 / 13 / 15 / 17 / 19 / 22. Body 15. Weights 400 and 600 only.

## Spacing and layout

4px base. Comfortable density: card padding 20, section gaps 24-32, table rows 10 vertical. Max content width 1200, centered. Two-column grid on desktop (main 2fr, aside 1fr), stacked below 900px.

Vary the rhythm. The same padding on every surface is monotony, not consistency: a pulse row
is not a log table and should not breathe like one. Weight follows stakes, so the number the
operator acts on outranks the number they merely note.

**Never nest a card in a card.** A container that already has a border and a surface does not
need its children boxed again; separate them with a hairline, a gap, or nothing at all. Boxes
inside boxes is the failure mode this console keeps drifting toward.

## Components

Cards: surface bg, 1px border, radius 10, padding 24, no shadow in dark (border carries elevation), soft shadow in light. Buttons: primary (accent bg, ink text), quiet (transparent, border), danger-quiet. Radius 8. Badges: tinted bg at 12-18% alpha + colored text, radius 999. Tabs: underline indicator, no pills. Inputs: raised bg, border, focus ring 2px accent at 40%.

## Motion

Curve: cubic-bezier(0.22, 1, 0.36, 1) (ease-out-quint) everywhere. Never bounce or elastic.
Opacity and transform only; never animate layout properties.

- **Feedback** 120-160ms. A press, a toggle, a hover.
- **State change** 160-200ms. A row leaving, a panel opening.
- **Counting** 480ms. A number travelling to its new value: the job is to convey a
  magnitude, and 200ms of that is a blur. Only when the value actually changed, and only
  for figures the operator is watching move.
- **Entrance** 240ms with a 40ms stagger, capped at six steps (~200ms total). One per
  navigation, never replayed by the 5s poll. A view arrives; it does not perform.
- **Exit** runs at 75% of the matching entrance. Leaving is quicker than arriving.

Motion carries meaning or it does not ship: a decision leaves the queue, a number moves to
its new value, a run shows it is running. Nothing pulses, blinks or loops idle. The
anti-reference stands: a screen that moves while nothing happens is a trading dashboard.

`prefers-reduced-motion: reduce` collapses transitions **and** animations to none, and every
state must be legible without them.

## Bans (project-level)

No gradients, no glassmorphism, no side-stripe borders, no modals (inline confirmation), no emoji in UI; icons are the owner's pixel-art set on ivory chips (image-rendering: pixelated), inline SVG (1.5px stroke, currentColor) for the rare glyph the set lacks, no spinners mid-content (skeletons).
