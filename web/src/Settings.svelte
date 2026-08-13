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
  import Segmented from "./Segmented.svelte";
  import Toggle from "./Toggle.svelte";
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

  // The four steps, as **multipliers of the brand saturation** — which is what `--ui-chroma` is:
  // `calc(0.065 * var(--ui-chroma))`, 1 being the palette as designed. They were written as chroma
  // values (0.06, 0.12, 0.2), so every step asked for a tenth of the colour, the differences between
  // them were invisible, and the control looked broken because it was. `medium` is 1 on purpose: it is
  // the shipped look, and the range's ceiling is the shipped page's own slider maximum of 1.5.
  const INTENSITY = [
    { key: "flat", chroma: 0 },
    { key: "subtle", chroma: 0.5 },
    { key: "medium", chroma: 1 },
    { key: "full", chroma: 1.5 },
  ];
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

  /** The theme is stored on this corparius, not in the browser: it follows the operator.
   *
   * Applied first, persisted second. It used to await the POST before touching a single custom
   * property, so every click on a swatch waited for a store write — which reads as a control that does
   * not work rather than one that is thorough. The server is still the record: its answer replaces the
   * optimistic value, and a refusal puts the previous one back.
   */
  async function setTheme(patch) {
    const previous = theme;
    theme = { ...(theme ?? {}), ...patch };
    applyTheme(theme);
    try {
      theme = await post("/api/theme", patch, { token });
      applyTheme(theme);
    } catch (e) {
      theme = previous;
      applyTheme(theme);
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
    <span class="toggle small">
      <Toggle
        checked={showAdvanced}
        label={t("cfg.advanced")}
        onchange={(next) => (showAdvanced = next)}
      />
      <span class="muted">{t("cfg.advanced")}</span>
    </span>

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
            <!-- Once, on the heading of the section it is about. It was a pill on every affected field —
                 eight identical pills in one screen — and then a bare sentence under the description,
                 which read as debug output. -->
            {#if fields.some((f) => f.restart_required)}
              <span class="badge plain">{t("cfg.restart")}</span>
            {/if}
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

          <div class="fields paired">
          {#each fields as f (f.key)}
            <label class="field" class:locked={!f.editable}>
              <span class="fname">{labelOf(f)}</span>

              {#if f.type === "bool"}
                {@const on = String(edited[f.key] ?? f.value ?? f.default) === "true"}
                <Toggle
                  checked={on}
                  disabled={!f.editable}
                  label={labelOf(f)}
                  onchange={(next) => (edited[f.key] = next ? "true" : "false")}
                />
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

              <!-- Everything that documents the field, in one element. Beside the label these wrapped to
                   a second line in French and staggered every input in the row by 30px; as three
                   separate grid children they landed in the same cell and drew on top of each other. -->
              <div class="fhelp">
                {#if !f.editable}
                  <span class="badge warn" title={t("cfg.envTip")}>{t("cfg.env")}</span>
                {/if}
                {#if helpOf(f)}
                  {@const help = helpOf(f)}
                  {@const cut = help.indexOf(". ")}
                  {#if cut > 0 && cut < help.length - 2}
                    <!-- The first sentence, then the rest on request. Every field carried three to six
                         lines of grey at one weight, so a screen of eighty fields was a document with
                         inputs in it and the eye had nothing to land on. The first sentence is the one
                         that says what the field is; the remainder is why, and why can wait. -->
                    <small class="lead"><Ticked text={help.slice(0, cut + 1)} /></small>
                    <details class="more">
                      <summary>{t("ops.more")}</summary>
                      <small class="muted"><Ticked text={help.slice(cut + 2)} /></small>
                    </details>
                  {:else}
                    <small class="lead"><Ticked text={help} /></small>
                  {/if}
                {/if}
                {#if f.help_url}
                  <a class="link small" href={f.help_url} target="_blank" rel="noreferrer noopener">
                    {t("cfg.stepOpen")}
                  </a>
                {/if}
                {#if refusals[f.key]}<small class="bad">{refusals[f.key]}</small>{/if}
              </div>
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
        <Segmented
          label={t("settings.theme")}
          value={theme?.mode ?? ""}
          options={[
            { value: "dark", label: t("settings.dark") },
            { value: "light", label: t("settings.light") },
          ]}
          onpick={(mode) => setTheme({ mode })}
        />
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
    <div class="field">
      <!-- The knob that makes "turn the colour off" still legible: chroma at 0 is greyscale, and the
           measured ramps still hold their contrast because only the chroma moves. -->
      <span class="fname">{t("settings.intensity")}</span>
      <!-- Named steps, not percentages. "0% 21% 43% 71% 100%" is the ramp's arithmetic showing through:
           nobody outside `tokens.css` knows what 43% of a chroma is, and four names are what the
           operator is choosing between. -->
      <Segmented
        fill
        label={t("settings.intensity")}
        value={INTENSITY.find((s) => Math.abs(Number(theme?.chroma ?? 1) - s.chroma) < 0.24)?.key ??
          "medium"}
        options={INTENSITY.map((s) => ({ value: s.key, label: t("settings." + s.key) }))}
        onpick={(key) => setTheme({ chroma: String(INTENSITY.find((s) => s.key === key).chroma) })}
      />
      <small class="muted">{t("settings.intensityHint")}</small>
    </div>
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
  /* Declared here, not in `console.css`: Svelte scopes `.rail button` to this component and that beats a
     global `.chip.on`, so the selected pill kept the muted colour and the unselected ones read as
     active. The winner has to be written where the loser lives. */
  .rail button.on { color: var(--accent-ink); }
  .warn-dot { background: var(--warn); }
  legend { display: flex; align-items: center; gap: 8px; }

  /* Three columns of fields at this card's width, each one label over control over documentation. The
     alternative — control on the left, documentation on the right — was tried and reverted: it needs a
     column count of one, and eighty single-file fields is the 5 000px page this replaced.

     `align-items: start` is what keeps a field whose help runs five lines from stretching its two
     neighbours to match. */
  .fields {
    display: grid;
    gap: 18px 28px;
    grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
    align-items: start;
  }
  .field { display: grid; gap: 5px; align-content: start; font-size: 13.5px; min-width: 0; }
  /* Everything that documents the field, in one child: as three grid children they landed in the same
     cell and drew on top of each other. */
  .fhelp { display: grid; gap: 5px; justify-items: start; }
  .fhelp small { font-size: 12px; line-height: 1.55; color: var(--muted); }
  /* The first sentence is a step up in contrast from the rest: it is the one a reader needs. */
  .fhelp .lead { color: var(--text); opacity: 0.78; }
  .fhelp .more > summary { cursor: pointer; font-size: 11.5px; color: var(--select); padding: 2px 0; }
  .fhelp .more[open] > summary { margin-bottom: 3px; }
  fieldset { border: 0; border-top: 1px solid var(--border); margin: 16px 0 0; padding: 14px 0 0; min-width: 0; }
  legend { padding: 0; font-size: 14px; font-weight: 600; color: var(--text); }
  .field > .fname { color: var(--muted); }
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
