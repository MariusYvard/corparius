<script>
  /**
   * The shell: pick a company, pick a language, hold the credential, show a tab.
   *
   * One tab so far, and that is deliberate — the plan's order is tab by tab so each one can be
   * looked at in a browser as it lands. A styled empty frame would say less about whether the
   * direction is right than one page an operator can actually read.
   *
   * Two things it does before anything else, and both come from the v1 contract:
   *
   *   * `GET /api/v1/meta` — the versions, so this can refuse a core too old for it rather than
   *     failing one request at a time, and `capabilities`, so a button is hidden instead of
   *     discovering a 404;
   *   * `GET /api/session` — whether a credential is required at all. Still the legacy path, and
   *     the one place this console reads one: it is the resource that exists to be readable before
   *     you can authenticate, and it has no v1 spelling yet.
   */
  import { onMount } from "svelte";
  import Overview from "./Overview.svelte";
  import { get, Refused } from "./api.js";
  import { LANGUAGES, load, translator } from "./i18n.js";

  // The starting language is resolved and its table awaited in `main.js`, before this mounts, so
  // the first paint is already in the right language.
  let { lang: initial } = $props();
  // svelte-ignore state_referenced_locally
  // Capturing the initial value is the intent, not a slip: `main.js` resolves the starting language
  // and awaits its table before mounting, and from here on the switcher below owns `lang`. The
  // warning is right to fire by default — reading a prop non-reactively usually is a mistake — so it
  // is silenced with the reason rather than left to sit in the build output where the next one hides.
  let lang = $state(initial);
  let t = $derived(translator(lang));

  let meta = $state(null);
  let companies = $state([]);
  let company = $state(localStorage.getItem("corparius-company") || "");
  let token = $state(localStorage.getItem("corparius-token") || "");
  let tokenRequired = $state(false);
  let failure = $state(null);

  // The contract this build was written against. A core that answers a different number is not
  // one this console can talk to, and saying so beats failing one request at a time.
  const SPEAKS = 1;

  async function choose(next) {
    await load(next);
    lang = next;
    localStorage.setItem("corparius-lang", next);
    document.documentElement.lang = next;
  }

  function pickCompany(slug) {
    company = slug;
    localStorage.setItem("corparius-company", slug);
  }

  function saveToken(value) {
    token = value.trim();
    localStorage.setItem("corparius-token", token);
    boot();
  }

  async function boot() {
    failure = null;
    try {
      const session = await get("/api/session", { revalidate: false });
      tokenRequired = Boolean(session.token_required);
      meta = await get("/api/v1/meta");
      const list = await get("/api/v1/companies", { token });
      companies = list.companies ?? [];
      if (!companies.includes(company)) pickCompany(companies[0] ?? "");
    } catch (e) {
      failure = e instanceof Refused ? e : new Refused(0, { error: { message: String(e) } });
    }
  }

  onMount(() => {
    document.documentElement.lang = lang;
    boot();
  });
</script>

<header>
  <div class="brand">
    <strong>corparius</strong> <span class="muted">{t("brand.console")}</span>
  </div>
  <div class="controls">
    {#if companies.length > 1}
      <select
        aria-label={t("header.company")}
        value={company}
        onchange={(e) => pickCompany(e.currentTarget.value)}
      >
        {#each companies as slug}<option value={slug}>{slug}</option>{/each}
      </select>
    {/if}
    <nav aria-label="language">
      {#each LANGUAGES as code}
        <button class="lang" onclick={() => choose(code)} aria-pressed={lang === code}>{code}</button>
      {/each}
    </nav>
  </div>
</header>

<main>
  {#if failure?.code === "unauthenticated" || (tokenRequired && !token)}
    <!-- The one form this console has. `unauthenticated` is a code, not a sentence, which is why
         this branch can exist at all: the old page matched on prose. -->
    <section class="card">
      <h2>{t("token.needed")}</h2>
      <form
        onsubmit={(e) => {
          e.preventDefault();
          saveToken(e.currentTarget.elements.token.value);
        }}
      >
        <input name="token" type="password" placeholder={t("token.placeholder")} />
        <button type="submit">{t("token.save")}</button>
      </form>
    </section>
  {:else if failure}
    <p class="banner">{t("conn.error")} {failure.message}</p>
  {:else if meta && meta.api_version !== SPEAKS}
    <!-- Refusing once, by version, rather than failing one request at a time. This is the whole
         reason `meta` carries three of them. -->
    <p class="banner">
      This console speaks v{SPEAKS} and this corparius answers v{meta.api_version}.
    </p>
  {:else if !meta}
    <p class="muted">{t("docs.reading")}</p>
  {:else if !company}
    <p class="muted">{t("wiz.title")}</p>
  {:else}
    <Overview {lang} {company} {token} />
  {/if}
</main>

<footer class="muted small">
  {#if meta}
    v{meta.app_version} · api {meta.api_version} · schema {meta.schema_version}
    {#if !meta.capabilities.durable_jobs}<span> · no durable jobs</span>{/if}
  {/if}
</footer>

<style>
  :global(body) {
    margin: 0;
    background: var(--bg);
    color: var(--text);
    font: 15px/1.55 var(--body, system-ui, sans-serif);
  }
  header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 1rem;
    padding: 0.8rem 1.25rem;
    border-bottom: 1px solid var(--border);
    background: var(--surface);
  }
  .controls { display: flex; align-items: center; gap: 0.6rem; }
  main { max-width: 46rem; margin: 0 auto; padding: 1.5rem 1.25rem; }
  footer { max-width: 46rem; margin: 0 auto; padding: 0 1.25rem 2rem; }
  .muted { color: var(--muted); }
  .small { font-size: 0.88rem; }
  select, input {
    background: var(--raised);
    color: var(--text);
    border: 1px solid var(--border-ui);
    border-radius: 6px;
    padding: 0.3rem 0.5rem;
    font: inherit;
  }
  button {
    background: var(--accent);
    color: var(--accent-ink);
    border: 1px solid transparent;
    border-radius: 6px;
    padding: 0.35rem 0.75rem;
    cursor: pointer;
    font: inherit;
  }
  button.lang { background: none; color: var(--muted); border-color: var(--border); padding: 0.2rem 0.5rem; }
  button.lang[aria-pressed="true"] { color: var(--text); border-color: var(--border-ui); }
  button:focus-visible, select:focus-visible, input:focus-visible {
    outline: 2px solid var(--select);
    outline-offset: 2px;
  }
  .card {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 1rem 1.1rem;
  }
  h2 { font-size: 0.82rem; text-transform: uppercase; letter-spacing: 0.07em; color: var(--muted); margin: 0 0 0.6rem; }
  form { display: flex; gap: 0.5rem; margin-top: 0.7rem; }
  .banner {
    border: 1px solid var(--danger);
    background: var(--danger-soft);
    color: var(--danger);
    padding: 0.6rem 0.85rem;
    border-radius: 8px;
  }
</style>
