<script>
  /**
   * A sentence whose backticks mean what they mean everywhere else.
   *
   * The core writes operator-facing prose with inline code in it — "Check `python -m corparius.cli
   * doctor`.", "On, `corparius apps serve` lets your apps call your LLM providers." — and both consoles
   * printed the backticks as characters. Three rows of the action log read ``Check `python -m
   * corparius.cli doctor`.`` on screen, which is the punctuation of a format nobody rendered.
   *
   * Split on the tick and alternate, rather than `{@html}` on a converted string. These strings carry
   * a model's output and a server's error text; building markup out of them would put a stranger's
   * characters into the DOM as HTML, and there is nothing this has to render that is worth that. An
   * odd number of ticks degrades to plain text, which is the honest failure.
   */
  let { text = "" } = $props();
  let parts = $derived(String(text ?? "").split("`"));
</script>

{#each parts as part, i}{#if i % 2 && i < parts.length - 1}<code>{part}</code>{:else}{part}{/if}{/each}
