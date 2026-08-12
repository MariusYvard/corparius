<script>
  /**
   * One switch, everywhere a setting is on or off.
   *
   * The product had two vocabularies for the same decision: Providers used native checkboxes for
   * "Mock mode", "Cloud enabled" and "Claude Code CLI", while Settings used a drawn switch for the same
   * class of boolean two tabs away. A blind review called it out as two controls for one concept, and it
   * is — the native box also drew Chromium's #3b3b3b on navy, which is the colour of nobody having
   * styled the page.
   *
   * `role="switch"` on a button rather than a styled checkbox: a switch takes effect immediately and a
   * checkbox is a value you submit, which is the distinction the ARIA roles exist to make. `aria-label`
   * is required, because the visible label is usually a sibling this component cannot see.
   */
  let { checked = false, disabled = false, label = "", onchange = undefined } = $props();
</script>

<button
  type="button"
  role="switch"
  class="toggle"
  aria-checked={checked}
  aria-label={label}
  {disabled}
  onclick={() => onchange?.(!checked)}
><i></i></button>

<style>
  .toggle {
    width: 40px;
    height: 22px;
    border-radius: 999px;
    padding: 0;
    flex: none;
    position: relative;
    background: var(--raised);
    border: 1px solid var(--border-ui);
  }
  .toggle i {
    position: absolute;
    top: 2px;
    left: 2px;
    width: 16px;
    height: 16px;
    border-radius: 999px;
    background: var(--muted);
    transition:
      transform var(--t-feedback) var(--ease),
      background-color var(--t-feedback) var(--ease);
  }
  .toggle[aria-checked="true"] { background: var(--accent); border-color: var(--accent); }
  .toggle[aria-checked="true"] i { transform: translateX(18px); background: var(--accent-ink); }
  .toggle:hover:not(:disabled) { background: var(--raised); border-color: var(--muted); }
  .toggle[aria-checked="true"]:hover:not(:disabled) { border-color: var(--accent); }
</style>
