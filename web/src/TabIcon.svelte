<script>
  /**
   * One glyph per tab, drawn rather than fetched.
   *
   * The shipped page carried pixel-art PNGs for five of the seven tabs and nothing for the other
   * two. A tab strip where two entries are missing their icon reads as unfinished rather than as
   * restrained, so these are line drawings on one 24-unit grid with one stroke weight — a set,
   * which is the property the PNGs could not have.
   *
   * Written out per id rather than `{@html}` from a table of path strings. The markup is a constant
   * either way, so this is not about safety; it is that a reader can see what "operations" looks
   * like by reading it, and an SVG hidden in a string is a thing nobody ever corrects.
   *
   * `aria-hidden`, always: every tab has its own label beside it, and an icon that announces itself
   * makes a screen reader say the name twice.
   */
  let { id } = $props();
</script>

<svg class="tab-glyph" viewBox="0 0 24 24" aria-hidden="true" stroke-linecap="round" stroke-linejoin="round">
  {#if id === "overview"}
    <!-- A trace: the pulse of a working day. -->
    <path d="M3 13h4l3-7 4 13 3-6h4" />
  {:else if id === "operations"}
    <!-- Three columns of a board, descending — proposed, approved, running. -->
    <path d="M4 5h4v15H4zM10 5h4v10h-4zM16 5h4v6h-4z" />
  {:else if id === "documents"}
    <!-- A page with its corner turned. -->
    <path d="M6 3h7l5 5v13H6zM13 3v5h5" />
  {:else if id === "providers"}
    <!-- A cloud, which is where all but one of them are. -->
    <path d="M7.5 18.5a4.25 4.25 0 0 1 .4-8.48 5.75 5.75 0 0 1 10.9 1.6 3.5 3.5 0 0 1-.8 6.88z" />
  {:else if id === "ceo"}
    <!-- A speech bubble: the one tab that answers back. -->
    <path d="M4 5h16v11H10l-6 4z" />
  {:else if id === "settings"}
    <!-- Sliders. Three tracks, three knobs at different positions. -->
    <path d="M3 7h6M13 7h8M3 13h12M19 13h2M3 19h4M11 19h10" />
    <circle cx="11" cy="7" r="1.9" />
    <circle cx="17" cy="13" r="1.9" />
    <circle cx="9" cy="19" r="1.9" />
  {:else if id === "plugins"}
    <!-- Two blocks and the seam between them. -->
    <path d="M4 4h7v7H4zM13 13h7v7h-7zM11 7.5h2M16.5 11v2" />
  {/if}
</svg>
