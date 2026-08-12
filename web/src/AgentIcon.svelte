<script>
  /**
   * One glyph per agent role, on the same grid and the same stroke as the tab icons.
   *
   * The shipped page had eleven pixel-art portraits for these, and three blind design reviews in a row
   * read them as emoji placeholder art — "a red heart for the social agent" — at 36px and at 20px. They
   * were removed rather than defended, which left the roles named only in text. This is the answer both
   * reviews actually asked for: a monochrome set at the same 24-unit grid, 1.7 stroke and optical size as
   * `TabIcon.svelte`, so an agent in the activity log and a tab in the nav belong to one drawing system.
   *
   * Written out per id rather than `{@html}` from a table: the markup is a constant either way, and a
   * reader can see what "competitor" looks like by reading it. An unknown role — a plugin's own — renders
   * nothing rather than a fallback box, because a shape that means "unrecognised" is worse than a name on
   * its own.
   *
   * `aria-hidden`, always: every one of these sits beside the role's name in text.
   */
  let { id = "", size = 15 } = $props();
</script>

<svg
  class="agent-glyph"
  width={size}
  height={size}
  viewBox="0 0 24 24"
  aria-hidden="true"
  fill="none"
  stroke="currentColor"
  stroke-width="1.7"
  stroke-linecap="round"
  stroke-linejoin="round"
>
  {#if id === "ceo"}
    <!-- A compass: the one that decides the direction. -->
    <circle cx="12" cy="12" r="8.5" />
    <path d="M15.5 8.5 10.5 10.5 8.5 15.5 13.5 13.5Z" />
  {:else if id === "social"}
    <!-- Two bubbles: talking in public. -->
    <path d="M3.5 5.5h11v7h-6l-5 3.5z" />
    <path d="M17 9h3.5v6.5h-2l-3 2.5v-2.5h-2.5" />
  {:else if id === "outreach"}
    <!-- An envelope, addressed to somebody who did not ask for it. -->
    <path d="M3 6h18v12H3zM3 6l9 7 9-7" />
  {:else if id === "support"}
    <!-- A lifebuoy. -->
    <circle cx="12" cy="12" r="8.5" />
    <circle cx="12" cy="12" r="3.6" />
    <path d="M6 6l3.5 3.5M18 6l-3.5 3.5M6 18l3.5-3.5M18 18l-3.5-3.5" />
  {:else if id === "ads"}
    <!-- A target, and the money that gets spent hitting it. -->
    <circle cx="12" cy="12" r="8.5" />
    <circle cx="12" cy="12" r="4" />
    <circle cx="12" cy="12" r="0.9" fill="currentColor" stroke="none" />
  {:else if id === "finance"}
    <!-- A banknote. -->
    <path d="M2.5 7h19v10h-19z" />
    <circle cx="12" cy="12" r="2.6" />
    <path d="M5.5 12h0.01M18.5 12h0.01" />
  {:else if id === "strategy"}
    <!-- A line going up, which is the claim a strategy makes. -->
    <path d="M3.5 19.5h17M6 16l4-5 3.5 3 5-7" />
    <path d="M18.5 7h-3.2M18.5 7v3.2" />
  {:else if id === "competitor"}
    <!-- Binoculars: watching somebody else. -->
    <circle cx="6.5" cy="15" r="3.8" />
    <circle cx="17.5" cy="15" r="3.8" />
    <path d="M10.3 15h3.4M6.5 11.2 8 5.5h3l0.6 5.9M17.5 11.2 16 5.5h-3l-0.6 5.9" />
  {:else if id === "design"}
    <!-- A pen nib. -->
    <path d="M5 19 8 9l8-4.5 4 4L15.5 16z" />
    <path d="M8 9l7.5 7M12 12.5 5 19" />
  {:else if id === "coder"}
    <!-- Angle brackets, which is what code looks like from across a room. -->
    <path d="M9 7 3.5 12 9 17M15 7l5.5 5L15 17" />
  {:else if id === "system"}
    <!-- The machine itself: a cog. -->
    <circle cx="12" cy="12" r="3.4" />
    <path
      d="M12 2.5v3M12 18.5v3M2.5 12h3M18.5 12h3M5.2 5.2l2.1 2.1M16.7 16.7l2.1 2.1M18.8 5.2l-2.1 2.1M7.3 16.7l-2.1 2.1"
    />
  {/if}
</svg>

<style>
  .agent-glyph { flex: none; color: var(--muted); vertical-align: -2px; }
</style>
