<script>
  /**
   * One control for "pick exactly one of these", with one seam and one outline.
   *
   * There were four spellings of this: the language pair in the header, the theme pair in Settings (two
   * loose buttons plus a text link), the section index, and the intensity steps. Loose buttons say "these
   * are independent actions"; a segmented control says "one of these is true", which is the actual claim
   * in all four places.
   *
   * The selected segment takes the accent fill and its ink. That is not decoration: in light mode the
   * previous treatment put a dark navy label on a saturated blue tint, and the *unselected* segment —
   * full-contrast text on the card — read as the active one.
   */
  /**
   * `quiet` is for the one of these that lives in the chrome rather than in a card.
   *
   * A review, unprompted, named the header's language pair as "the highest-contrast element on every
   * page — a saturated blue block louder than the primary nav and louder than '2 waiting on you'".
   * That is what an accent fill does when it sits above every page instead of inside one: the accent
   * is supposed to mean "the choice you just made here", and the language is a standing state that
   * nobody came to this page to change. Same control, same seam, no shout.
   */
  let {
    options = [],
    value = "",
    onpick = undefined,
    label = "",
    fill = false,
    quiet = false,
  } = $props();
</script>

<div class="seg" class:fill class:quiet role="group" aria-label={label}>
  {#each options as option (option.value)}
    <button
      type="button"
      aria-pressed={option.value === value}
      onclick={() => onpick?.(option.value)}
    >{option.label}</button>
  {/each}
</div>

<style>
  .seg {
    display: inline-flex;
    border: 1px solid var(--border-ui);
    border-radius: 8px;
    overflow: hidden;
    max-width: 100%;
  }
  /* Each segment takes an equal share when the control is told to fill. Sized to their labels, four
     segments left 300px of empty track beside them and read as a control that failed to lay out. */
  .seg.fill { display: flex; width: 100%; }
  .seg.fill button { flex: 1; }
  .seg button {
    border: 0;
    border-radius: 0;
    padding: 6px 13px;
    color: var(--muted);
    font-size: 13px;
    font-weight: 600;
    white-space: nowrap;
  }
  .seg button + button { border-left: 1px solid var(--border-ui); }
  .seg button[aria-pressed="true"] { background: var(--accent); color: var(--accent-ink); }
  .seg button[aria-pressed="true"]:hover { background: var(--accent); }
  /* Chrome, not content: a raised surface and full-contrast text instead of the accent fill. Still
     unmistakably the selected one — it is the only segment that is not muted — without being the
     loudest thing on a page it does not belong to. */
  .seg.quiet { border-color: var(--border); }
  .seg.quiet button + button { border-left-color: var(--border); }
  .seg.quiet button[aria-pressed="true"] { background: var(--raised); color: var(--text); }
  .seg.quiet button[aria-pressed="true"]:hover { background: var(--raised); }
  .seg.quiet button:not([aria-pressed="true"]):hover { color: var(--text); }
</style>
