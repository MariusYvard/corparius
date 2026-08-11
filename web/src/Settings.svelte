<script>
  /**
   * The fifth tab: everything corparius reads, plus backup and the console's own look.
   *
   * ## The form is generated, never written out
   *
   * 80 fields across eight groups, and not one of them is named in this file. `GET /api/v1/settings`
   * describes each one — type, group, default, bilingual label and help — and this renders what it is
   * given. A hand-written form would be a second copy of the registry, and
   * `tests/test_registries.py` exists because this project has already paid for that twice: a field
   * the console offered that nothing read, and a value the code read that the console could not set.
   *
   * Three facts a client cannot work out for itself, so the payload carries them:
   *
   *   * **`value` is `null` for a secret** and `configured` says whether there is one. A payload that
   *     echoed a credential would put it in every client's cache and every proxy log.
   *   * **`editable` is `source !== "env"`.** The process environment outranks anything the console
   *     writes, so a field it owns is shown *disabled with the reason* rather than offered and
   *     silently ignored. That is the providers tab's `shadowed` lesson, resolved per field.
   *   * **`restart_required`** for a bootstrap key: it lands in `.env` because it must be readable
   *     before the store opens, so it applies next start. Saying so is the difference between a
   *     setting that looks broken and one that is waiting.
   *
   * ## Clearing is not the same as blanking
   *
   * An empty registry field goes in `unset`, which deletes the row so the layer below shows through
   * again — what an operator asking for the default means. A provider credential is the opposite and
   * lives on the providers tab for that reason: `app_settings.CREDENTIALS` keeps a blank one stored,
   * because clearing the row would let `.env` resurrect a key they had just revoked.
   */
  import { get, post, Refused } from "./api.js";
  import { applyTheme } from "./theme.js";
  import Ticked from "./Ticked.svelte";
  import { fill, translator } from "./i18n.js";

  let { lang, token = "" } = $props();
  let t = $derived(translator(lang));

  let registry = $state(null);
  let theme = $state(null);
  let failure = $state(null);
  let busy = $state("");
  let said = $state("");
  let backup = $state(null);
  let mailTest = $state(null);
  let showAdvanced = $state(false);
  // Edits in flight, keyed by field. Not seeded from the payload: a refresh must never overwrite what
  // somebody is halfway through typing, and an untouched field simply is not submitted.
  let edited = $state({});
  // Per-field refusals, so each sentence lands next to the input that caused it rather than in one
  // banner. `detail.errors` carries them apart for exactly this.
  let refusals = $state({});

  async function load() {
    try {
      const [r, th] = await Promise.all([
        get("/api/v1/settings", { token }),
        get("/api/theme", { revalidate: false, token }),
      ]);
      registry = r;
      theme = th;
      failure = null;
    } catch (e) {
      failure = e instanceof Refused ? e : new Refused(0, { error: { message: String(e) } });
    }
  }

  // Loaded, not polled: a settings registry does not change under the operator's hands.
  $effect(() => {
    load();
  });

  /** The fields of one group, advanced ones only when asked for. */
  function fieldsOf(group) {
    return (registry?.fields ?? []).filter(
      (f) => f.group === group && (showAdvanced || !f.advanced),
    );
  }

  const labelOf = (f) => (lang === "fr" ? f.label_fr : f.label_en) || f.key;
  const helpOf = (f) => (lang === "fr" ? f.help_fr : f.help_en) || "";
  const groupLabel = (g) => (lang === "fr" ? g.label_fr : g.label_en) || g.name;
  const groupHelp = (g) => (lang === "fr" ? g.help_fr : g.help_en) || "";

  async function save() {
    busy = "save";
    said = "";
    refusals = {};
    // An empty string on a registry field means *clear it*, which is `unset` rather than a blank
    // value — the row goes, and the layer below shows through again.
    const values = {};
    const unset = [];
    for (const [key, raw] of Object.entries(edited)) {
      if (String(raw).trim() === "") unset.push(key);
      else values[key] = raw;
    }
    if (!Object.keys(values).length && !unset.length) {
      said = t("toast.nothing");
      busy = "";
      return;
    }
    try {
      const done = await post("/api/v1/settings", { values, unset }, { token });
      registry = done;
      edited = {};
      said = t("cfg.saved");
      if (done.restart_required?.length) said = `${said} ${t("cfg.restartNote")}`;
      // Stored, and still overridden. The environment belongs to whoever started the process, so
      // this is the honest answer rather than a switch that springs back.
      if (done.shadowed?.length) {
        said = `${said} ${fill(t("cfg.shadowedNote"), { keys: done.shadowed.join(", ") })}`;
      }
    } catch (e) {
      failure = e;
      for (const line of e.detail?.errors ?? []) {
        // `CORP_X: expected a whole number, got 'y'` — the service names the field first, which is
        // what lets each sentence go back to its own input.
        const [key] = String(line).split(":");
        if (key) refusals[key.trim()] = line;
      }
    } finally {
      busy = "";
    }
  }

  /** Fill the derived mail fields from a provider preset. Saved only when the operator saves. */
  function applyPreset(id) {
    const preset = (registry?.mail_presets ?? []).find((p) => p.id === id);
    if (!preset) return;
    const map = {
      CORP_SMTP_HOST: preset.host,
      CORP_SMTP_PORT: preset.port,
      CORP_IMAP_HOST: preset.imap_host,
      CORP_IMAP_PORT: preset.imap_port,
    };
    for (const [key, value] of Object.entries(map)) {
      if (value !== undefined && value !== null) edited[key] = String(value);
    }
    // A provider that sends but has no mailbox to read gets a different sentence, because "reading
    // is not set up" is a fact about the provider rather than something the operator forgot.
    said = preset.imap_host ? t("cfg.presetFilled") : t("cfg.presetSendOnly");
  }

  async function runBackup() {
    busy = "backup";
    try {
      backup = await post("/api/v1/backup", {}, { token });
    } catch (e) {
      failure = e;
    } finally {
      busy = "";
    }
  }

  async function testMail() {
    busy = "mail";
    mailTest = null;
    try {
      const to = edited.CORP_OUTREACH_TEST_TO ?? "";
      mailTest = (await post("/api/test/mail", { to }, { token })).result;
    } catch (e) {
      failure = e;
    } finally {
      busy = "";
    }
  }

  /** The theme is stored on this corparius, not in the browser: it follows the operator. */
  async function setTheme(patch) {
    try {
      theme = await post("/api/theme", patch, { token });
      applyTheme(theme);
    } catch (e) {
      failure = e;
    }
  }

  // Applied through `theme.js`, which the shell also uses: this tab owns the *controls*, not the
  // rule that a theme is applied. Two copies of that rule is how an operator's light theme came to
  // arrive only after they opened this tab.
  $effect(() => {
    if (theme) applyTheme(theme);
  });

  let warnGroups = $derived(new Set((registry?.groups ?? []).filter((g) => g.warn).map((g) => g.name)));
  // The groups that have a field to show, which is what the rail lists and what the page renders.
  let shownGroups = $derived((registry?.groups ?? []).filter((g) => fieldsOf(g.name).length));

  // How many fields differ from what the server holds. `edited` accumulates every keystroke, including
  // ones typed back to the original value, so counting its keys would report changes that are not
  // changes — and a Save that lights up for a no-op is a Save nobody trusts.
  let dirty = $derived(
    Object.entries(edited).filter(([key, value]) => {
      const field = (registry?.fields ?? []).find((f) => f.key === key);
      if (!field) return false;
      return String(value) !== String(field.value ?? field.default ?? "");
    }).length,
  );

  // One section at a time. An index over a 5 100px page is a table of contents; a page that shows one
  // of eight sections is a form. The anchors were plain text that read as prose rather than as
  // navigation, and they left the scroll exactly as long as it was.
  let section = $state("");
  let current = $derived(
    shownGroups.find((g) => g.name === section) ?? shownGroups[0] ?? null,
  );
</script>

{#if failure}
  <p class="banner danger">
    {failure.message}
    {#if failure.code}<code>{failure.code}</code>{/if}
  </p>
{/if}
{#if said}<p class="banner ok">{said}</p>{/if}

{#if !registry}
  <p class="muted">{t("docs.reading")}</p>
{:else}
  <!-- Full width, three columns of fields. It was a 1.45/1 split, which put an 80-field form in two
       300px columns and left 460px of empty background running beside it for 4 600px — so the page was
       both cramped and mostly empty. Backup and the console's own preferences follow the form as
       ordinary sections; they are short, and a rail that ends after 1 400px of a 6 000px page is a
       rail somebody scrolls away from and cannot find again. -->
  <section class="card">
    <div>
      <h2>{t("cfg.title")}</h2>
      <p class="desc">{t("cfg.desc")}</p>
    </div>
    <!-- Its own row. Beside the description it was a flex sibling that never shrinks, so the French
         label squeezed the paragraph into a 130px ribbon eight lines tall next to half an empty card. -->
    <label class="toggle small">
      <input type="checkbox" checked={showAdvanced} onchange={() => (showAdvanced = !showAdvanced)} />
      <span class="muted">{t("cfg.advanced")}</span>
    </label>

    <!-- Said once. It was rendered under every group that touches real-world effects, which on this
         page is three identical full-width boxes in one scroll — and three identical warnings teach
         an operator to skip all of them. -->
    {#if warnGroups.size}
      <p class="banner warn small">{lang === "fr" ? registry.warning.fr : registry.warning.en}</p>
    {/if}

    <!-- The way in, and it stays. Twelve sections with no index is a page somebody scrolls past rather
         than reads; an index that scrolls away with the first screen is one they read once. -->
    <nav class="rail sticky-top" aria-label={t("cfg.title")}>
      {#each shownGroups as group (group.name)}
        <button
          class="chip"
          class:on={current?.name === group.name}
          onclick={() => (section = group.name)}
        >
          {groupLabel(group)}
          {#if warnGroups.has(group.name)}<span class="dot warn-dot"></span>{/if}
        </button>
      {/each}
    </nav>

    {#each current ? [current] : [] as group (group.name)}
      {@const fields = fieldsOf(group.name)}
      {#if fields.length}
        <fieldset id={`g-${group.name}`}>
          <legend>
            {groupLabel(group)}
            {#if warnGroups.has(group.name)}<span class="dot warn-dot"></span>{/if}
          </legend>
          <p class="desc small">{groupHelp(group)}</p>

          {#if group.preset}
            <!-- The hosts and ports are derived, which is the whole point: an operator picks their
                 provider and gives an address and an app password. -->
            <label class="field">
              <span>{t("cfg.preset")}</span>
              <select onchange={(e) => applyPreset(e.currentTarget.value)}>
                <option value="">{t("cfg.presetPick")}</option>
                {#each registry.mail_presets as preset (preset.id)}
                  <option value={preset.id}>{preset.label}</option>
                {/each}
              </select>
            </label>
          {/if}

          <div class="fields">
          {#each fields as f (f.key)}
            <label class="field" class:locked={!f.editable}>
              <span class="fname">{labelOf(f)}</span>

              {#if f.type === "bool"}
                {@const on = String(edited[f.key] ?? f.value ?? f.default) === "true"}
                <span class="switch">
                  <button
                    type="button"
                    role="switch"
                    aria-checked={on}
                    disabled={!f.editable}
                    onclick={() => (edited[f.key] = on ? "false" : "true")}
                  ><i></i></button>
                </span>
              {:else if f.type === "select"}
                <select
                  disabled={!f.editable}
                  value={edited[f.key] ?? f.value ?? f.default}
                  onchange={(e) => (edited[f.key] = e.currentTarget.value)}
                >
                  {#each f.choices ?? [] as choice (choice)}<option value={choice}>{choice}</option>{/each}
                </select>
              {:else if f.secret || f.type === "password"}
                <!-- Never the value. `configured` is the only thing the server will say about a
                     secret, so the placeholder is the whole report. -->
                <input
                  type="password"
                  autocomplete="off"
                  disabled={!f.editable}
                  placeholder={f.configured ? t("cfg.isSet") : t("cfg.notSet")}
                  value={edited[f.key] ?? ""}
                  oninput={(e) => (edited[f.key] = e.currentTarget.value)}
                />
              {:else}
                <input
                  type={f.type === "int" || f.type === "float" ? "number" : "text"}
                  step={f.type === "float" ? "any" : undefined}
                  disabled={!f.editable}
                  title={edited[f.key] ?? f.value ?? ""}
                  placeholder={f.default || "—"}
                  value={edited[f.key] ?? f.value ?? ""}
                  oninput={(e) => (edited[f.key] = e.currentTarget.value)}
                />
              {/if}

              <!-- Under the field, not in the label. As label suffixes these two wrapped to a second
                   line in French and staggered every input in the row by 30px. -->
              <small class="meta">
                {#if f.restart_required}<span class="badge">{t("cfg.restart")}</span>{/if}
                {#if !f.editable}<span class="badge warn" title={t("cfg.envTip")}>{t("cfg.env")}</span>{/if}
              </small>
              {#if helpOf(f)}<small class="muted"><Ticked text={helpOf(f)} /></small>{/if}
              {#if f.help_url}
                <a class="link small" href={f.help_url} target="_blank" rel="noreferrer noopener">
                  {t("cfg.stepOpen")}
                </a>
              {/if}
              {#if refusals[f.key]}<small class="bad">{refusals[f.key]}</small>{/if}
            </label>
          {/each}
          </div>

          {#if group.test === "mail"}
            <div class="actions">
              <button disabled={busy === "mail"} onclick={testMail}>
                {busy === "mail" ? t("cfg.testing") : t("cfg.testMail")}
              </button>
            </div>
            {#if mailTest}
              <p class="small" class:good={mailTest.ok} class:bad={!mailTest.ok}>{mailTest.detail}</p>
            {/if}
          {/if}
        </fieldset>
      {/if}
    {/each}

    <div class="sticky-bottom">
      <button class="primary" disabled={busy === "save" || !dirty} onclick={save}>{t("cfg.save")}</button>
      {#if dirty}
        <span class="count">{dirty}</span>
        <span class="muted small">{t("cfg.unsaved")}</span>
      {/if}
    </div>
  </section>

  <div class="grid half">
  <section class="card">
    <h2>{t("bk.title")}</h2>
    <p class="desc">{t("bk.desc")}</p>
    <!-- Not boilerplate: no key leaves in plaintext, and the archive still holds the operator's
         companies and their journal. A button that offered this silently would be handing over a
         file whose contents they do not know. -->
    <p class="banner warn small">{t("bk.warn")}</p>
    <div class="actions">
      <button disabled={busy === "backup"} onclick={runBackup}>
        {busy === "backup" ? t("bk.running") : t("bk.run")}
      </button>
    </div>
    {#if backup}
      <p class="small">
        {t("bk.done")}: <code>{backup.name}</code>
        <span class="muted">{Math.round(backup.size / 1024)} kB</span>
      </p>
    {/if}
  </section>

  <section class="card">
    <h2>{t("settings.title")}</h2>
    <p class="desc">{t("settings.desc")}</p>
    <div class="field">
      <span>{t("settings.theme")}</span>
      <div class="actions">
        {#each ["dark", "light"] as mode (mode)}
          <button
            aria-pressed={theme?.mode === mode}
            onclick={() => setTheme({ mode })}
          >{t("settings." + mode)}</button>
        {/each}
        <button class="link" onclick={() => setTheme({ mode: "", hue: "", chroma: "" })}>
          {t("settings.reset")}
        </button>
      </div>
    </div>
    <div class="field">
      <span class="fname">{t("settings.accent")}</span>
      <!-- Swatches, because a hue slider shows you a rail rather than the colour you are choosing. Eight
           steps around the wheel, each painted in the hue it sets, and the current one ringed. -->
      <div class="hues">
        {#each [264, 226, 196, 166, 132, 86, 32, 350] as hue (hue)}
          <button
            class="hue"
            style="background: oklch(0.62 0.19 {hue})"
            aria-label={`${t("settings.accent")} ${hue}`}
            aria-pressed={Number(theme?.hue ?? 264) === hue}
            onclick={() => setTheme({ hue: String(hue) })}
          ></button>
        {/each}
      </div>
    </div>
    <label class="field">
      <!-- The knob that makes "turn the colour off" still legible: chroma at 0 is greyscale, and the
           measured ramps still hold their contrast because only the chroma moves. -->
      <span class="fname">
        {t("settings.intensity")}
        <span class="count">{Number(theme?.chroma ?? 0.12).toFixed(2)}</span>
      </span>
      <input
        type="range"
        min="0"
        max="0.3"
        step="0.01"
        value={theme?.chroma ?? 0.12}
        onchange={(e) => setTheme({ chroma: e.currentTarget.value })}
      />
    </label>
  </section>
  </div>
{/if}

<style>
  /* Only Settings' own. The card, the buttons, the inputs, the badges and the grids are the console's
     language and live in `console.css`. */

  /* A group is a set of fields, and 80 of them in one column was a page somebody scrolled rather than
     read. Two-up from 640px of card width, which is what turns the registry from a wall into a form. */
  /* The section index. The marked ones are the sections whose keys reach the real world. */
  .rail { display: flex; flex-wrap: wrap; gap: 4px 2px; }
  .rail button { display: inline-flex; align-items: center; gap: 6px; font-size: 13px; color: var(--muted); }
  .rail button:hover { color: var(--select); }
  .warn-dot { background: var(--warn); }
  legend { display: flex; align-items: center; gap: 8px; }

  .fields { display: grid; gap: 14px 20px; grid-template-columns: repeat(auto-fill, minmax(272px, 1fr)); }
  fieldset { border: 0; border-top: 1px solid var(--border); margin: 16px 0 0; padding: 14px 0 0; min-width: 0; }
  legend { padding: 0; font-size: 14px; font-weight: 600; color: var(--text); }
  .field { display: grid; gap: 4px; align-content: start; font-size: 13.5px; min-width: 0; }
  .field > .fname { color: var(--muted); }
  /* Empty most of the time, and it collapses when it is: `:empty` rather than a conditional wrapper, so
     a field with neither chip costs no vertical space. */
  .field .meta { display: flex; gap: 6px; flex-wrap: wrap; }
  .field .meta:empty { display: none; }
  .field input, .field select { width: 100%; }
  /* A field the environment owns is shown, not hidden: an operator looking for it needs to find it
     and read why it is not theirs to change here. */
  .field.locked { opacity: 0.72; }
  .toggle { display: flex; gap: 8px; align-items: center; white-space: nowrap; }
  .actions { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }
  /* The selected option wins on contrast. It was a faint tint with muted text beside an
     unselected option in full-contrast white, so the unselected one read as active. */
  button[aria-pressed="true"] { background: var(--accent); border-color: var(--accent); color: var(--accent-ink); }
  input:disabled, select:disabled { opacity: 0.6; cursor: not-allowed; }
  input[type="range"] { padding: 0; accent-color: var(--select); }
  .hues { display: flex; gap: 8px; flex-wrap: wrap; }
  .hue {
    width: 26px;
    height: 26px;
    padding: 0;
    border-radius: 999px;
    border: 1px solid var(--border-ui);
    transition: transform var(--t-feedback) var(--ease);
  }
  .hue:hover { transform: scale(1.12); background: inherit; }
  .hue[aria-pressed="true"] { outline: 2px solid var(--select); outline-offset: 2px; }
  small { font-size: 12.5px; }
  .good { color: var(--ok); }
  .bad { color: var(--danger); }
  a.link { color: var(--select); }
</style>
