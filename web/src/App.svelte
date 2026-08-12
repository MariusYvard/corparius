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
  // The mark as geometry rather than as a bitmap; see `Mark.svelte` for why the raster went.
  import Mark from "./Mark.svelte";
  import Segmented from "./Segmented.svelte";
  import Ticked from "./Ticked.svelte";

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

  // While the core is unreachable, keep asking. A restart takes a few seconds and the console finding
  // that out by itself is the difference between "it broke" and "it was busy". Only while `failure` is a
  // transport failure — a 401 or a version mismatch is an answer, and retrying an answer is a loop.
  $effect(() => {
    if (!failure || failure.code) return;
    const timer = setInterval(boot, 3000);
    return () => clearInterval(timer);
  });
</script>

<div class="shell">
<header class="top">
  <div class="wrap">
    <div class="brand">
      <Mark />
      <span class="name">corparius</span>
      <span class="dim">{t("brand.console")}</span>
    </div>
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
    <!-- The shared control: one outline, one seam, one answer. Two loose buttons said the two
         languages were two independent toggles — and this component's own copy of the rule was the
         reason the *unselected* segment read as active in light mode. -->
    <Segmented
      label="language"
      value={lang}
      options={LANGUAGES.map((code) => ({ value: code, label: code }))}
      onpick={choose}
    />
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
    <!-- A state, not a banner. When the core is not answering there is nothing else on the page, so a red
         strip in the top-left corner of an empty window was the whole design of the most common failure
         an operator will ever see. It says what happened, what it probably is, and keeps trying — a
         restarting server comes back on its own, and having to press reload to find that out is the
         console making its problem the operator's. -->
    <section class="down">
      <Mark size={44} />
      <h1>{t("conn.title")}</h1>
      <p class="desc"><Ticked text={t("conn.hint")} /></p>
      <p class="reason mono">{failure.message}</p>
      <div class="actions">
        <button class="primary" onclick={boot}>{t("conn.retry")}</button>
        <span class="muted small">{t("conn.retrying")}</span>
      </div>
    </section>
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
      <!-- The page's own top. Every tab went from a 76px header straight into a card, so the largest
           text on any screen was a 16.5px card title and nothing said where you were but a 2px tab
           underline. The subtitle is a key per tab rather than a reused sentence: seven tabs that all
           describe themselves the same way describe none of themselves. -->
      <header class="page-head">
        <h1>{t("nav." + shown.id)}</h1>
        <p class="desc">{t("sub." + shown.id)}</p>
      </header>
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

  /* The credential form is the one thing an operator may see before anything else, so it is centred
     and narrow rather than a full-width card with an input floating at the top of it. */
  .gate { max-width: 30rem; margin: 8vh auto 0; }

  /* The unreachable state: centred, in the middle of the window, with the mark to say the console itself
     is fine and it is the server that is missing. */
  .down {
    max-width: 34rem;
    margin: 12vh auto 0;
    display: grid;
    justify-items: center;
    text-align: center;
    gap: 14px;
  }
  .down h1 { font-size: 21px; font-weight: 650; letter-spacing: -0.015em; }
  .down .desc { margin: 0; }
  .down .reason { color: var(--danger); background: var(--danger-soft); border-radius: 8px; padding: 7px 12px; }
  .down .actions { display: flex; gap: 12px; align-items: center; flex-wrap: wrap; justify-content: center; }
  .gate form { display: flex; gap: 8px; }
  .gate input { flex: 1; }
</style>
