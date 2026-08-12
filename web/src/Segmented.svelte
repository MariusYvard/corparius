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
  let { options = [], value = "", onpick = undefined, label = "" } = $props();
</script>

<div class="seg" role="group" aria-label={label}>
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
</style>
