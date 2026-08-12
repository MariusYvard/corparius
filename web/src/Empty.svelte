<script>
  /**
   * One empty state, everywhere.
   *
   * There were five on the Operations tab alone, in four treatments: an inset filled slab, the word
   * "Empty" repeated five times under bare rules, and two unstyled paragraphs. On the Overview the
   * filled version read as a broken image — a 150×170 grey rectangle with centred text in it, which is
   * the exact silhouette of an image that failed to load.
   *
   * So: one line, quiet, left-aligned, with no fill, no reserved height and **no glyph**. The first version drew a circle with a
   * diagonal through it, which is a prohibition sign: "No payments yet" read as *blocked*, and five of
   * them across a kanban row read as five failures. A domain mark per state — a receipt, a file, a card
   * — would be right and is four drawings nobody has made; a ban symbol is worse than nothing.
   *
   * `slim` is the same component at column scale: five of these side by side in a kanban must not each
   * be 120px tall.
   */
  let { text = "", slim = false } = $props();
</script>

<div class="empty" class:slim>
  <p>{text}</p>
</div>

<style>
  /* No reserved height and no centring. It was a 108px box with a sentence in the middle of it, which
     is a placeholder frame — and in a stretched card it grew to 150px of nothing. One line where the
     content would have been says the same thing and takes the room it needs. */
  .empty { padding: 4px 0 2px; color: var(--muted); }
  .empty p { margin: 0; font-size: 13px; max-width: 68ch; }
  .empty.slim { padding: 8px 12px 10px; }
  .empty.slim p { font-size: 12px; }
</style>
