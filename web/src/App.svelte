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
  import TabIcon from "./TabIcon.svelte";
  import CEO from "./CEO.svelte";
  import Documents from "./Documents.svelte";
  import Operations from "./Operations.svelte";
  import Plugins from "./Plugins.svelte";
  import Overview from "./Overview.svelte";
  import Providers from "./Providers.svelte";
  import Settings from "./Settings.svelte";
  import { get, Refused } from "./api.js";
  import { LANGUAGES, load, translator } from "./i18n.js";
  import { loadTheme } from "./theme.js";
  // The wordmark, byte for byte the one the shipped page carries inline. Imported rather than
  // inlined so Vite emits it as a file the server already knows how to serve, and so the two
  // consoles cannot end up showing two different marks.
  import wordmark from "./wordmark.png";

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

  // The tabs that exist, in the order they are rebuilt. One per commit, so each can be looked at in
  // a browser as it lands — a styled empty frame would say less about whether the direction is right
  // than one page an operator can read. The remaining `nav.*` keys are in the table already and get
  // their entry when their component does; listing a name with nothing behind it would be a tab that
  // opens onto nothing, which is the same lie as a button that does nothing.
  const TABS = [
    { id: "overview", component: Overview },
    { id: "operations", component: Operations },
    { id: "documents", component: Documents },
    { id: "providers", component: Providers },
    { id: "ceo", component: CEO },
    { id: "settings", component: Settings },
    { id: "plugins", component: Plugins },
  ];
  let tab = $state(localStorage.getItem("corparius-tab") || "overview");
  let shown = $derived(TABS.find((entry) => entry.id === tab) ?? TABS[0]);

  function pickTab(id) {
    tab = id;
    localStorage.setItem("corparius-tab", id);
  }

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
      // The theme, here rather than in the tab that edits it. It is stored on this corparius so it
      // follows the operator; reading it only when Settings mounts meant every other tab rendered
      // dark first and then changed under them.
      loadTheme(token);
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

<div class="shell">
<header class="top">
  <div class="wrap">
    <h1 class="brand">
      <img src={wordmark} alt="corparius" />
      <span class="dim">{t("brand.console")}</span>
    </h1>
    <span class="spacer"></span>
    {#if companies.length > 1}
      <select
        aria-label={t("header.company")}
        value={company}
        onchange={(e) => pickCompany(e.currentTarget.value)}
      >
        {#each companies as slug}<option value={slug}>{slug}</option>{/each}
      </select>
    {/if}
    <!-- A segmented pair rather than two loose buttons: the two languages are one control with one
         answer, and two separate outlines said they were two independent toggles. -->
    <div class="seg" role="group" aria-label="language">
      {#each LANGUAGES as code}
        <button onclick={() => choose(code)} aria-pressed={lang === code}>{code}</button>
      {/each}
    </div>
  </div>
</header>

{#if meta && meta.api_version === SPEAKS && company && !(tokenRequired && !token) && failure?.code !== "unauthenticated"}
  <!-- `role="tablist"` on a `div`, not on the `<nav>` it started as: `nav` already carries an
       implicit `navigation` role and Svelte's a11y pass says so. Full pattern rather than half of
       it — `aria-controls` and a `tabpanel` — because tabs a screen reader cannot follow are
       decoration, and the shipped page had this right.

       It lives outside `main` and spans the window, which is what the 46rem column could not do: a
       tab strip inset in a narrow column reads as a widget on a page rather than as the navigation
       of an application. -->
  <nav class="tabs" aria-label={t("brand.console")}>
    <div class="wrap" role="tablist" aria-label={t("brand.console")}>
      {#each TABS as entry (entry.id)}
        <button
          role="tab"
          id={`tab-${entry.id}`}
          aria-controls={`panel-${entry.id}`}
          aria-selected={tab === entry.id}
          onclick={() => pickTab(entry.id)}
        >
          <TabIcon id={entry.id} />{t("nav." + entry.id)}
        </button>
      {/each}
    </div>
  </nav>
{/if}

<main class="wrap">
  {#if failure?.code === "unauthenticated" || (tokenRequired && !token)}
    <!-- The one form this console has. `unauthenticated` is a code, not a sentence, which is why
         this branch can exist at all: the old page matched on prose. -->
    <section class="card gate">
      <h2>{t("token.needed")}</h2>
      <form
        onsubmit={(e) => {
          e.preventDefault();
          saveToken(e.currentTarget.elements.token.value);
        }}
      >
        <input name="token" type="password" placeholder={t("token.placeholder")} />
        <button class="primary" type="submit">{t("token.save")}</button>
      </form>
    </section>
  {:else if failure}
    <p class="banner danger">{t("conn.error")} {failure.message}</p>
  {:else if meta && meta.api_version !== SPEAKS}
    <!-- Refusing once, by version, rather than failing one request at a time. This is the whole
         reason `meta` carries three of them. -->
    <p class="banner danger">
      This console speaks v{SPEAKS} and this corparius answers v{meta.api_version}.
    </p>
  {:else if !meta}
    <p class="muted">{t("docs.reading")}</p>
  {:else if !company}
    <p class="muted">{t("wiz.title")}</p>
  {:else}
    <!-- Keyed on the tab id so switching tabs remounts rather than reusing state. Two tabs poll
         different resources on different cadences; a reused component would keep the other one's
         interval running against the wrong endpoints. -->
    {#key shown.id}
      <!-- The page's own title. It uses the tab's name rather than a second string per tab: a subtitle
           per tab would be seven more keys in two languages saying what the cards under them already
           say. -->
      <h1 class="page-title">{t("nav." + shown.id)}</h1>
      <div
        class="enter"
        role="tabpanel"
        id={`panel-${shown.id}`}
        aria-labelledby={`tab-${shown.id}`}
      >
        <!-- `onTab` lets a card whose call to action is "Open Providers" actually open it. Only
             Overview reads it; the others ignore an extra prop. -->
        <shown.component {lang} {company} {token} onTab={pickTab} />
      </div>
    {/key}
  {/if}
</main>

<footer class="foot">
  <div class="wrap"><div class="rule">
  {#if meta}
    v{meta.app_version} · api {meta.api_version} · schema {meta.schema_version}
    {#if !meta.capabilities.durable_jobs}<span> · no durable jobs</span>{/if}
  {/if}
  </div></div>
</footer>
</div>

<style>
  /* Only what belongs to the shell. Everything shared — the card, the buttons, the inputs, the tab
     strip, the wrap — is in `console.css`, because eight components each growing their own `.card`
     is how they drifted apart in the first place. */

  /* The two languages are one control, so they share one outline and one seam. */
  .seg { display: inline-flex; border: 1px solid var(--border-ui); border-radius: 8px; overflow: hidden; }
  .seg button {
    border: 0;
    border-radius: 0;
    padding: 6px 12px;
    color: var(--muted);
    font-size: 13px;
    font-weight: 600;
  }
  .seg button + button { border-left: 1px solid var(--border-ui); }
  .seg button[aria-pressed="true"] { background: var(--select-soft); color: var(--select); }

  /* The credential form is the one thing an operator may see before anything else, so it is centred
     and narrow rather than a full-width card with an input floating at the top of it. */
  .gate { max-width: 30rem; margin: 8vh auto 0; }
  .gate form { display: flex; gap: 8px; }
  .gate input { flex: 1; }
</style>
