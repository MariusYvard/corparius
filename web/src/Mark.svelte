<script>
  /**
   * The corparius mark: one parent, three reports.
   *
   * ## Where it started
   *
   * A 213×136 raster wordmark scaled to 46px with a glow behind it. A blind review called it "a
   * low-res raster sprite … the first pixel a stranger sees and it says dev placeholder", and it was
   * right twice: the art was downscaled to a third of its size, and the word *corparius* was baked
   * into the bitmap, so the brand's own name rendered as four illegible pixels instead of as text.
   * Redrawing it as paths fixed that. It did not fix what four more reviews then said, in almost the
   * same words each time — "the only saturated multi-hue object in an otherwise restrained blue-grey
   * palette", "muddy rather than distinctive", "reads as stock clip-art".
   *
   * ## What was actually wrong, measured
   *
   * Two things, and neither was the concept.
   *
   * **The lightness spread.** The four sampled fills are `#51b436 #f8d509 #fb7f25 #318ada`. In oklch
   * those sit at L 0.685, 0.876, 0.726 and 0.620 — a spread of **0.256**. Four colours that far apart
   * in lightness cannot read as a set; they read as four unrelated primaries, which is exactly what
   * "clip-art" means when a designer says it. The hues are kept to the tenth of a degree (139.7, 97.0,
   * 50.5, 249.6 — this is still the same logo) and the lightness spread is closed to **0.12**. Yellow
   * keeps the widest allowance because a dark yellow is olive, and olive is a different colour.
   *
   * **The outline.** Every box carried a 2.4px near-black stroke. That is the sticker convention —
   * it is what makes a shape read as printed rather than as drawn — and it was doing the work that
   * the fills should do. The boxes are flat now, with a hairline in `currentColor` at low opacity
   * purely so the shapes hold their edges on a white header, where the fills measure 1.8–2.6:1. On
   * the dark header they measure 6.0–8.8:1 and the hairline is barely visible, which is correct: it
   * is an edge, not a border.
   *
   * The wiring is thinner and quieter than the nodes for the same reason a wire is thinner than a box
   * on a real org chart — it is the relationship, not the thing.
   *
   * The four fills are literal on purpose and this is the one file in `web/src` allowed that: a brand
   * mark is not a theme. `tests/test_console_tokens.py` names the exception and checks that nothing
   * else takes it.
   */
  let { size = 30 } = $props();
</script>

<svg
  class="mark"
  width={size}
  height={size * 0.8}
  viewBox="0 0 40 32"
  aria-hidden="true"
  fill="none"
>
  <!-- The wiring, under the nodes: a drop from the parent, a bus across, three drops down. Thinner
       than the nodes and half-transparent — it is the relationship, not the thing. -->
  <path
    d="M20 11.5v4.5M6.4 16h27.2M6.4 16v3.4M20 16v3.4M33.6 16v3.4"
    stroke="currentColor"
    stroke-width="1.7"
    stroke-linecap="round"
    stroke-linejoin="round"
    opacity="0.5"
  />
  <!-- The parent, wider than its reports, then the three of them. `paint-order` is what lets the
       hairline sit inside the shape rather than doubling its visual weight. -->
  <g stroke="currentColor" stroke-width="0.9" stroke-opacity="0.22" paint-order="stroke fill">
    <rect x="12.4" y="1.4" width="15.2" height="9.4" rx="2.6" fill="#70bf5c" />
    <rect x="1.4" y="19.6" width="10" height="11" rx="2.6" fill="#e1c333" />
    <rect x="15" y="19.6" width="10" height="11" rx="2.6" fill="#fc8c44" />
    <rect x="28.6" y="19.6" width="10" height="11" rx="2.6" fill="#4aa3f7" />
  </g>
</svg>

<style>
  .mark { display: block; flex: none; color: var(--text); }
</style>
