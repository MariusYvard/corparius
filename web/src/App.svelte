<script>
  /**
   * The shell, and deliberately only the shell.
   *
   * This commit proves the chain end to end — Vite builds into the package, `paths` finds the
   * output in all three distribution modes, the stdlib server serves it, the bundle reads
   * `/api/v1/meta` and renders its own labels from the i18n JSON — and it does that before any tab
   * is rebuilt, because the packaging is the part with real risk and it is cheaper to prove on a
   * page with nothing on it.
   *
   * What it shows is what a thin client has to read first: the three versions, so it can refuse a
   * core too old for it, and the capabilities, so it hides a button rather than discovering a 404.
   */
  import { onMount } from "svelte";
  import { get, Refused } from "./api.js";
  import { LANGUAGES, load, translator } from "./i18n.js";

  // The starting language is resolved and its table awaited in `main.js`, before this mounts, so
  // the first paint is already in the right language.
  let { lang: initial } = $props();
  let lang = $state(initial);
  let meta = $state(null);
  let failure = $state(null);
  let t = $derived(translator(lang));

  async function choose(next) {
    await load(next);
    lang = next;
    localStorage.setItem("corparius-lang", next);
    document.documentElement.lang = next;
  }

  onMount(async () => {
    document.documentElement.lang = lang;
    try {
      meta = await get("/api/v1/meta");
    } catch (e) {
      // The envelope's `code` is what a client acts on. `unauthenticated` means ask for a token;
      // anything else means say what happened and stop, rather than retrying a request that will
      // fail the same way.
      failure = e instanceof Refused ? { code: e.code, message: e.message } : { code: "", message: String(e) };
    }
  });
</script>

<main>
  <header>
    <h1>corparius <span class="muted">{t("brand.console")}</span></h1>
    <nav aria-label="language">
      {#each LANGUAGES as code}
        <button onclick={() => choose(code)} aria-pressed={lang === code}>{code}</button>
      {/each}
    </nav>
  </header>

  {#if failure}
    <p class="failure">{t("conn.error")} {failure.message}{#if failure.code} <code>{failure.code}</code>{/if}</p>
  {:else if !meta}
    <p class="muted">{t("docs.reading")}</p>
  {:else}
    <dl class="versions">
      <dt>api</dt><dd>{meta.api_version}</dd>
      <dt>app</dt><dd>{meta.app_version}</dd>
      <dt>schema</dt><dd>{meta.schema_version}</dd>
    </dl>
    <ul class="caps">
      {#each Object.entries(meta.capabilities) as [name, on]}
        <li class:on>{name}<span>{on ? "yes" : "no"}</span></li>
      {/each}
    </ul>
  {/if}
</main>

<style>
  /* Deliberately unstyled beyond legibility. The 513 lines of CSS in the shipped page become design
     tokens in the next commit, from DESIGN.md's measured ramps and contrasts; inventing a look here
     would be a look thrown away. */
  :global(body) {
    margin: 0;
    font: 15px/1.5 system-ui, sans-serif;
    background: #14110f;
    color: #f5f0e8;
  }
  main { max-width: 42rem; margin: 0 auto; padding: 2rem 1.25rem; }
  header { display: flex; align-items: baseline; justify-content: space-between; gap: 1rem; }
  h1 { font-size: 1.4rem; font-weight: 600; margin: 0 0 1.5rem; }
  .muted { opacity: 0.6; font-weight: 400; }
  nav button { background: none; border: 1px solid #4a423b; color: inherit; padding: 0.2rem 0.6rem; cursor: pointer; }
  nav button[aria-pressed="true"] { background: #4a423b; }
  .failure { color: #f0a882; }
  .versions { display: grid; grid-template-columns: auto 1fr; gap: 0.2rem 1rem; margin: 0 0 1.5rem; }
  dt { opacity: 0.6; }
  dd { margin: 0; font-variant-numeric: tabular-nums; }
  .caps { list-style: none; padding: 0; margin: 0; display: grid; gap: 0.2rem; }
  .caps li { display: flex; justify-content: space-between; border-bottom: 1px solid #2a251f; padding: 0.35rem 0; opacity: 0.55; }
  .caps li.on { opacity: 1; }
  .caps span { font-variant-numeric: tabular-nums; }
</style>
