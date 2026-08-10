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
      applyTheme();
    } catch (e) {
      failure = e;
    }
  }

  function applyTheme() {
    const root = document.documentElement;
    // `tokens.css` keys light off `[data-theme="light"]` and treats `:root` as dark, so the attribute
    // has to be written for a light-mode operator to get light at all. The rebuilt console never set
    // it, which meant every operator got dark whatever they had chosen.
    if (theme?.mode) root.setAttribute("data-theme", theme.mode);
    else root.removeAttribute("data-theme");
    for (const [name, key] of [
      ["--ui-hue", "hue"],
      ["--ui-chroma", "chroma"],
    ]) {
      if (theme?.[key]) root.style.setProperty(name, theme[key]);
      else root.style.removeProperty(name);
    }
  }

  $effect(() => {
    if (theme) applyTheme();
  });

  let warnGroups = $derived(new Set((registry?.groups ?? []).filter((g) => g.warn).map((g) => g.name)));
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
  <section class="card">
    <div class="head">
      <div>
        <h2>{t("cfg.title")}</h2>
        <p class="desc">{t("cfg.desc")}</p>
      </div>
      <label class="toggle small">
        <input type="checkbox" checked={showAdvanced} onchange={() => (showAdvanced = !showAdvanced)} />
        <span class="muted">{t("cfg.advanced")}</span>
      </label>
    </div>

    {#each registry.groups as group (group.name)}
      {@const fields = fieldsOf(group.name)}
      {#if fields.length}
        <fieldset>
          <legend>{groupLabel(group)}</legend>
          <p class="desc small">{groupHelp(group)}</p>
          {#if warnGroups.has(group.name)}
            <p class="banner warn small">
              {lang === "fr" ? registry.warning.fr : registry.warning.en}
            </p>
          {/if}

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

          {#each fields as f (f.key)}
            <label class="field" class:locked={!f.editable}>
              <span>
                {labelOf(f)}
                {#if f.restart_required}<span class="chip">{t("cfg.restart")}</span>{/if}
                {#if !f.editable}<span class="chip warn" title={t("cfg.envTip")}>{t("cfg.env")}</span>{/if}
              </span>

              {#if f.type === "bool"}
                <select
                  disabled={!f.editable}
                  value={edited[f.key] ?? f.value ?? f.default}
                  onchange={(e) => (edited[f.key] = e.currentTarget.value)}
                >
                  <option value="true">true</option>
                  <option value="false">false</option>
                </select>
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
                  placeholder={f.default}
                  value={edited[f.key] ?? f.value ?? ""}
                  oninput={(e) => (edited[f.key] = e.currentTarget.value)}
                />
              {/if}

              {#if helpOf(f)}<small class="muted">{helpOf(f)}</small>{/if}
              {#if f.help_url}
                <a class="link small" href={f.help_url} target="_blank" rel="noreferrer noopener">
                  {t("cfg.stepOpen")}
                </a>
              {/if}
              {#if refusals[f.key]}<small class="bad">{refusals[f.key]}</small>{/if}
            </label>
          {/each}

          {#if group.test === "mail"}
            <div class="actions">
              <button class="quiet" disabled={busy === "mail"} onclick={testMail}>
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

    <div class="actions">
      <button disabled={busy === "save"} onclick={save}>{t("cfg.save")}</button>
    </div>
  </section>

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
            class="quiet"
            aria-pressed={theme?.mode === mode}
            onclick={() => setTheme({ mode })}
          >{t("settings." + mode)}</button>
        {/each}
        <button class="link" onclick={() => setTheme({ mode: "", hue: "", chroma: "" })}>
          {t("settings.reset")}
        </button>
      </div>
    </div>
    <label class="field">
      <span>{t("settings.accent")}</span>
      <input
        type="range"
        min="0"
        max="360"
        value={theme?.hue ?? 250}
        onchange={(e) => setTheme({ hue: e.currentTarget.value })}
      />
    </label>
    <label class="field">
      <!-- The knob that makes "turn the colour off" still legible: chroma at 0 is greyscale, and the
           measured ramps still hold their contrast because only the chroma moves. -->
      <span>{t("settings.intensity")}</span>
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
{/if}

<style>
  /* Tokens only; `tests/test_console_tokens.py` asserts it. */
  .card {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 1rem 1.1rem;
    margin: 0 0 1rem;
  }
  .head { display: flex; gap: 1rem; justify-content: space-between; align-items: flex-start; }
  h2 {
    font-size: 0.82rem;
    text-transform: uppercase;
    letter-spacing: 0.07em;
    color: var(--muted);
    margin: 0 0 0.35rem;
  }
  .desc { color: var(--muted); font-size: 0.9rem; margin: 0 0 0.9rem; }
  fieldset { border: 0; border-top: 1px solid var(--border); margin: 0.9rem 0 0; padding: 0.8rem 0 0; }
  legend { padding: 0 0.4rem 0 0; font-size: 0.9rem; color: var(--text); }
  .field { display: grid; gap: 0.25rem; margin: 0 0 0.8rem; font-size: 0.9rem; }
  .field > span { display: flex; gap: 0.35rem; align-items: center; flex-wrap: wrap; }
  /* A field the environment owns is shown, not hidden: an operator looking for it needs to find it
     and read why it is not theirs to change here. */
  .field.locked { opacity: 0.72; }
  .toggle { display: flex; gap: 0.4rem; align-items: center; white-space: nowrap; }
  .actions { display: flex; gap: 0.4rem; flex-wrap: wrap; align-items: center; margin-top: 0.4rem; }
  button {
    background: var(--accent);
    color: var(--accent-ink);
    border: 1px solid transparent;
    border-radius: 6px;
    padding: 0.35rem 0.75rem;
    cursor: pointer;
    font: inherit;
  }
  button.quiet { background: none; color: var(--text); border-color: var(--border-ui); }
  button.quiet[aria-pressed="true"] { border-color: var(--accent); color: var(--accent); }
  button.link { background: none; border: 0; color: var(--accent); text-decoration: underline; padding: 0.2rem 0; }
  button:disabled { opacity: 0.45; cursor: default; }
  button:focus-visible, input:focus-visible, select:focus-visible, a:focus-visible {
    outline: 2px solid var(--select);
    outline-offset: 2px;
  }
  input, select {
    background: var(--raised);
    color: var(--text);
    border: 1px solid var(--border-ui);
    border-radius: 6px;
    padding: 0.3rem 0.5rem;
    font: inherit;
  }
  input:disabled, select:disabled { opacity: 0.6; cursor: not-allowed; }
  input[type="range"] { padding: 0; }
  input[type="checkbox"] { width: auto; }
  small { font-size: 0.84rem; }
  .muted { color: var(--muted); }
  .small { font-size: 0.86rem; }
  .good { color: var(--ok); }
  .bad { color: var(--danger); }
  a.link { color: var(--accent); }
  .banner { padding: 0.6rem 0.85rem; border-radius: 8px; margin: 0 0 1rem; border: 1px solid; }
  .banner.danger { border-color: var(--danger); background: var(--danger-soft); color: var(--danger); }
  .banner.warn { border-color: var(--warn); background: var(--warn-soft); color: var(--warn); }
  .banner.ok { border-color: var(--ok); background: var(--ok-soft); color: var(--ok); }
  .chip {
    background: var(--raised);
    border: 1px solid var(--border-ui);
    border-radius: 999px;
    padding: 0 0.45rem;
    font-size: 0.76rem;
    color: var(--muted);
  }
  .chip.warn { color: var(--warn); border-color: var(--warn); }
</style>
