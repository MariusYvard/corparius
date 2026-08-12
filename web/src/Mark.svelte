<script>
  /**
   * The corparius mark, as geometry.
   *
   * It was a 213×136 raster wordmark scaled to 46px with a glow behind it, and a blind design review
   * called it "a low-res raster sprite … the first pixel a stranger sees and it says dev placeholder".
   * It was right twice over: the art was being downscaled to a third of its size, and the word
   * *corparius* was baked into the bitmap, so the brand's own name rendered as four illegible pixels
   * instead of as text.
   *
   * This is the same mark — `docs/icons/logo-corparius-mark.png`, an org chart: one parent, three
   * reports — redrawn as paths. The four fills are **sampled from that file**, not chosen:
   * #51b436, #f8d509, #fb7f25, #318ada on a black rule. Nothing here is a new logo; it is the existing
   * one at a size where it is a drawing rather than a smudge, and the name beside it is now a string
   * the operator's font renders.
   *
   * `currentColor` for the rules rather than black, so the mark holds together on a navy header as
   * well as on a white one — the one departure from the bitmap, and the reason it needs no halo.
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
  <!-- The wiring, under the boxes: a drop from the parent, a bus across, three drops down. -->
  <path
    d="M20 9v7M6.5 16h27M6.5 16v5M20 16v5M33.5 16v5"
    stroke="currentColor"
    stroke-width="2.4"
    stroke-linecap="square"
  />
  <!-- The parent, then its three reports, left to right. -->
  <rect x="13.2" y="1.2" width="13.6" height="9.6" rx="1" fill="#51b436" stroke="currentColor" stroke-width="2.4" />
  <rect x="1.2" y="20.2" width="10.6" height="10.6" rx="1" fill="#f8d509" stroke="currentColor" stroke-width="2.4" />
  <rect x="14.7" y="20.2" width="10.6" height="10.6" rx="1" fill="#fb7f25" stroke="currentColor" stroke-width="2.4" />
  <rect x="28.2" y="20.2" width="10.6" height="10.6" rx="1" fill="#318ada" stroke="currentColor" stroke-width="2.4" />
</svg>

<style>
  .mark { display: block; flex: none; color: var(--text); }
</style>
