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
  import { get, post, Refused } from "./api.js";
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

  // Making a company, from the header that switches between them. There was no way to do it from
  // this console at all: the picker listed what existed and stopped there, so the answer to "start a
  // second company" was the terminal or the old page. Three fields, which is what
  // `company.validate` actually requires: a name, what it sells, and a line about it. Everything
  // else takes a default from the same validator the editor uses, because a wizard that asked for
  // twelve would be a wall in front of the one gesture that has to be easy.
  let making = $state(false);
  let madeName = $state("");
  let madeLine = $state("");
  let madeProduct = $state("");
  let makeFailed = $state("");
  let makeBusy = $state(false);
  let dialog = $state(null);

  // The flag drives the element, in one place. Calling `showModal()` on an element that is already
  // open throws, and `close()` on a closed one fires `close` again, so both are guarded: this effect
  // has to be able to run whenever anything else in the component changes.
  $effect(() => {
    if (!dialog) return;
    if (making && !dialog.open) dialog.showModal();
    if (!making && dialog.open) dialog.close();
  });

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

  /**
   * Which panels exist in the document. A panel is built the first time it is *wanted* and is never
   * torn down again.
   *
   * ## Why this replaced `{#key shown.id}`
   *
   * Keying on the tab id remounted the component on every switch, which threw away its data and left
   * an empty frame on screen until the fetch came back. Measured on the real console, panel height in
   * the frames after a click:
   *
   * ```text
   *   operations   49px → 578px at 146ms → 610px at 238ms
   *   providers    49px → 1479px at 149ms → 1598px at 2173ms   (the Ollama probe)
   *   settings     49px → 1380px at 119ms
   *   plugins      49px → 641px at 61ms
   * ```
   *
   * Four of seven tabs opened as a 49-pixel shell and then grew by a factor of twelve to thirty. That
   * is what "loading in fits and starts" is, mechanically: not a slow request — 61ms is not slow —
   * but a layout that starts at nothing and jumps to its real size after it. And the data was already
   * in `api.js`'s cache, so most of those refetches answered 304 and rebuilt a view that had been
   * thrown away for nothing.
   *
   * The remount was there for a real reason, stated in the comment it replaces: two tabs poll
   * different resources on different cadences, and a component left mounted would keep polling the
   * wrong endpoints. That is answered directly instead — every tab takes `active`, and a poller that
   * is not the current tab is torn down while its state stays. The interval is what must stop; the
   * rendered view is what must not.
   */
  let built = $state([tab]);

  function want(id) {
    if (!built.includes(id)) built = [...built, id];
  }

  function pickTab(id) {
    want(id);
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

  async function makeCompany() {
    const name = madeName.trim();
    if (!name || makeBusy) return;
    makeBusy = true;
    makeFailed = "";
    try {
      // `lang` goes with it: a company created from the French console writes French, and the
      // charter, the site copy and every agent prompt read that field. Leaving it out would make
      // the operator's own language a setting they have to find afterwards.
      const made = await post(
        "/api/v1/companies",
        { name, product: madeProduct.trim(), one_liner: madeLine.trim(), lang },
        { token },
      );
      companies = made.companies ?? [...companies, made.slug];
      pickCompany(made.slug);
      making = false;
      madeName = "";
      madeLine = "";
      madeProduct = "";
    } catch (e) {
      // Kept in the dialog rather than thrown at the page: a refused name is something to correct
      // in the field it came from, and replacing the console with an error screen would lose it.
      makeFailed = e instanceof Refused ? e.message : String(e);
    } finally {
      makeBusy = false;
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
    <!-- Outside the `length > 1` guard on purpose: an operator with exactly one company has no
         picker, and they are the one most likely to want a second.

         `wiz.newOption` rather than a new string. The old page put "+ New company…" *inside* the
         picker as an extra option, which is where an operator learned to look for it, and the
         wording is theirs. It is a button here because a `<select>` that sometimes performs an
         action instead of selecting is a control that lies about what it is. -->
    <button class="quiet new-co" onclick={() => (making = true)}>{t("wiz.newOption")}</button>
    <!-- The shared control: one outline, one seam, one answer. Two loose buttons said the two
         languages were two independent toggles — and this component's own copy of the rule was the
         reason the *unselected* segment read as active in light mode. -->
    <Segmented
      label="language"
      quiet
      value={lang}
      options={LANGUAGES.map((code) => ({ value: code, label: code }))}
      onpick={choose}
    />
  </div>
</header>

<!-- A real `<dialog>`, driven by `showModal()` rather than by the `open` attribute. The distinction
     is the whole reason to use the element: `open` renders it in the normal flow with no backdrop,
     no focus trap and no Escape, which is a `<div>` wearing a dialog's name. `showModal()` is what
     the platform gives, and every one of those behaviours written by hand is a thing to get wrong.
     `onclose` keeps the flag in step with the dismissals this component never hears about. -->
<dialog class="make-co" bind:this={dialog} onclose={() => (making = false)}>
  <form
    onsubmit={(e) => {
      e.preventDefault();
      makeCompany();
    }}
  >
    <h2>{t("company.new")}</h2>
    <p class="muted">{t("wiz.desc")}</p>
    <label for="new-co-name">{t("wiz.name")}</label>
    <!-- svelte-ignore a11y_autofocus -->
    <input id="new-co-name" bind:value={madeName} autocomplete="off" autofocus required />
    <!-- The product, and it is not optional however much a two-field dialog would like it to be:
         `company.validate` refuses an offer with no product, so a form that omitted it would post,
         be refused, and show "offer.product is required" to somebody who was never asked. Measured
         against the running console, which is how it was found. -->
    <label for="new-co-product">{t("wiz.product")}</label>
    <input
      id="new-co-product"
      bind:value={madeProduct}
      placeholder={t("wiz.productPh")}
      autocomplete="off"
      required
    />
    <label for="new-co-line">{t("company.oneLiner")}</label>
    <input id="new-co-line" bind:value={madeLine} autocomplete="off" />
    {#if makeFailed}<p class="bad">{makeFailed}</p>{/if}
    <div class="row">
      <button type="button" class="quiet" onclick={() => (making = false)}>{t("task.cancel")}</button>
      <button
        type="submit"
        class="primary"
        disabled={makeBusy || !madeName.trim() || !madeProduct.trim()}
      >
        {t("wiz.create")}
      </button>
    </div>
  </form>
</dialog>

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
          onpointerenter={() => want(entry.id)}
          onfocus={() => want(entry.id)}
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
    <!-- The heading is `shown`, the panels are `built`. Only one is ever visible; the others keep
         their scroll position, their open rows and their filter text, which is the second half of
         what "instant" means to somebody clicking back and forth. -->
    <!-- The page's own top. Every tab went from a 76px header straight into a card, so the largest
         text on any screen was a 16.5px card title and nothing said where you were but a 2px tab
         underline. The subtitle is a key per tab rather than a reused sentence: seven tabs that all
         describe themselves the same way describe none of themselves. -->
    <header class="page-head">
      <h1>{t("nav." + shown.id)}</h1>
      <p class="desc">{t("sub." + shown.id)}</p>
    </header>
    {#each TABS as entry (entry.id)}
      {#if built.includes(entry.id)}
        <!-- `enter` plays once, when the panel is built, because that is the only time there is
             anything to cover: a return visit has its content already and an animation on it would
             be 440ms of theatre in front of a view that was ready. -->
        <div
          class="enter"
          role="tabpanel"
          id={`panel-${entry.id}`}
          aria-labelledby={`tab-${entry.id}`}
          hidden={entry.id !== tab}
        >
          <!-- `onTab` lets a card whose call to action is "Open Providers" actually open it. Only
               Overview reads it; the others ignore an extra prop.
               `active` is the half that lets a panel survive being left: it says whether this is the
               tab in front of the operator, and every poller in here is torn down when it is not. -->
          <entry.component
            {lang}
            {company}
            {token}
            active={entry.id === tab}
            onTab={pickTab}
          />
        </div>
      {/if}
    {/each}
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
