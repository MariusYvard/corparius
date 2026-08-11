<script>
  /**
   * The seventh and last tab: what extends corparius, and what this company knows in prose.
   *
   * Two things on one tab because they are the same act from the operator's side — adding capability
   * that corparius did not write. A plugin binds one of seven declared seams and adds a provider, a
   * tool, a template or an agent. A skill adds knowledge to a prompt.
   *
   * ## The number this panel exists for
   *
   * A skill that names no tool is **unscoped**, and an unscoped skill rides on every prompt of every
   * agent — 3 815 characters a turn, measured on the owner's own company. `corparius skills list`
   * could report that from a terminal and offer nothing to do about it; the one write here is giving a
   * skill a tool list so it travels only with the tools it is about.
   *
   * A skill declaring `always:` is counted in the bill and **not** badged as a problem. It is a
   * deliberate choice — a guardrail meant to be on every prompt — and a warning on a deliberate choice
   * is a warning an operator learns to ignore.
   *
   * ## Two things a client must not offer
   *
   * **Installing an unverified plugin.** That path is CLI-only behind an explicit opt-in, because it
   * runs unaudited third-party code. A button here would read as ordinary and would not be.
   *
   * **Editing a skill.** A skill is a file the operator wrote, and this console is not going to become
   * a second, worse text editor. The panel shows the path and what the loader will cut; the editing
   * happens where the file lives.
   *
   * ## Restart is always required, and always said
   *
   * A seam is bound at import, so a plugin enabled now changes nothing until the process restarts.
   * `restart_required` comes back on every write and is shown — a panel that said "Done" and left the
   * operator waiting for a provider that is not going to appear would be worse than one that refused.
   */
  import { get, post, Refused } from "./api.js";
  import { fill, translator } from "./i18n.js";

  let { lang, company, token = "" } = $props();
  let t = $derived(translator(lang));

  let data = $state(null);
  let failure = $state(null);
  let busy = $state("");
  let said = $state("");
  // Which skill's tool picker is open, and the tools ticked in it.
  let scoping = $state("");
  let ticked = $state([]);

  async function load() {
    try {
      data = await get(`/api/v1/plugins?company=${encodeURIComponent(company ?? "")}`, { token });
      failure = null;
    } catch (e) {
      failure = e instanceof Refused ? e : new Refused(0, { error: { message: String(e) } });
    }
  }

  // Loaded, not polled: a plugin list changes when the operator changes it, and a restart is needed
  // for any of it to take effect anyway.
  $effect(() => {
    load();
  });

  async function act(action, name) {
    busy = `${action}:${name}`;
    said = "";
    try {
      const done = await post("/api/v1/plugins", { action, name }, { token });
      data = done;
      // Always true, always shown. The alternative is an operator waiting for a seam that binds at
      // import and will not appear until the next start.
      said = done.restart_required ? t("pl.saved") : t("toast.saved");
    } catch (e) {
      failure = e;
    } finally {
      busy = "";
    }
  }

  function openScope(skill) {
    scoping = skill.name;
    ticked = [...(skill.tools ?? [])];
  }

  async function saveScope(name) {
    if (!ticked.length) {
      said = t("sk.scopeNone");
      return;
    }
    busy = `scope:${name}`;
    said = "";
    try {
      data = await post("/api/v1/skills/scope", { name, tools: ticked, company }, { token });
      said = t("sk.scopeSaved");
      scoping = "";
    } catch (e) {
      failure = e;
    } finally {
      busy = "";
    }
  }

  function toggle(tool) {
    ticked = ticked.includes(tool) ? ticked.filter((x) => x !== tool) : [...ticked, tool];
  }

  let installed = $derived(data?.installed ?? []);
  let offers = $derived(
    (data?.registry ?? []).filter((r) => !installed.some((p) => p.name === r.name)),
  );
  let skills = $derived(data?.skills ?? []);
</script>

{#if failure}
  <p class="banner danger">
    {failure.message}
    {#if failure.code}<code>{failure.code}</code>{/if}
  </p>
{/if}
{#if said}<p class="banner ok">{said}</p>{/if}

{#if !data}
  <p class="muted">{t("docs.reading")}</p>
{:else}
  <!-- Two columns: the registry is sparse by design and the skills list is the long one.

       There was a dot texture behind this panel, for presence. It is gone: the banners on this page use
       a 20%-alpha tint, so the dots showed *through* them and read as a rendering fault. A texture that
       fights the content in front of it is worse than a plain surface. -->
  <div class="grid cols">
  <section class="card">
    <div>
    <h2>{t("pl.title")}</h2>
    <p class="desc">{t("pl.intro")}</p>
    <!-- Said before the list rather than after: an operator who enables a plugin while the feature is
         off has done everything right and nothing will happen. -->
    {#if !data.enabled}<p class="banner warn small">{t("pl.off")}</p>{/if}
    <p class="banner warn small">{t("pl.unverified")}</p>

    <h3>{t("pl.installed")}</h3>
    <div class="rows">
    {#each installed as plugin (plugin.name)}
      <article class="row">
        <div>
          <strong>{plugin.name}</strong>
          <span class="muted">{plugin.version}</span>
          {#if plugin.verified}
            <span class="badge ok">{t("pl.verified")}</span>
          {:else}
            <span class="badge danger">{t("pl.unverifiedTag")}</span>
          {/if}
          {#if plugin.disabled}<span class="badge">{t("pl.disabled")}</span>{/if}
          {#if plugin.loaded}<span class="badge ok">{t("pl.loaded")}</span>{/if}
          {#if plugin.description}<p class="muted small">{plugin.description}</p>{/if}
          <!-- Which seams it binds. Seven exist; naming the ones a plugin uses is the difference
               between "a plugin" and "something that can answer your model calls". -->
          {#if plugin.kinds?.length}
            <p class="small muted">{plugin.kinds.join(" · ")}</p>
          {/if}
        </div>
        <div class="actions">
          {#if plugin.disabled}
            <button disabled={busy === `enable:${plugin.name}`} onclick={() => act("enable", plugin.name)}>
              {t("pl.enable")}
            </button>
          {:else}
            <button disabled={busy === `disable:${plugin.name}`} onclick={() => act("disable", plugin.name)}>
              {t("pl.disable")}
            </button>
          {/if}
          <button
            class="quiet"
            disabled={busy === `remove:${plugin.name}`}
            onclick={() => {
              // Confirmed, because removing deletes files the operator installed. Not a typed
              // confirmation like deleting a company — a plugin is reinstallable from the registry.
              if (confirm(fill(t("pl.confirmRemove"), { n: plugin.name }))) act("remove", plugin.name);
            }}
          >{t("pl.remove")}</button>
        </div>
      </article>
    {/each}
    </div>
    {#if installed.length === 0}<p class="empty">{t("pl.none")}</p>{/if}

    <h3>{t("pl.available")}</h3>
    <div class="rows">
    {#each offers as offer (offer.name)}
      <article class="row">
        <div>
          <strong>{offer.name}</strong>
          {#if offer.description}<p class="muted small">{offer.description}</p>{/if}
        </div>
        <button disabled={busy === `install:${offer.name}`} onclick={() => act("install", offer.name)}>
          {t("pl.install")}
        </button>
      </article>
    {/each}
    </div>
    {#if offers.length === 0}<p class="empty">{t("pl.regEmpty")}</p>{/if}
    </div>
  </section>

  <section class="card">
    <h2>{t("sk.title")}</h2>
    <p class="desc">{t("sk.intro")}</p>
    {#if !data.skills_enabled}
      <p class="banner warn small">{t("sk.off")}</p>
    {:else}
      <!-- The bill, in front of the list. This is the whole reason the panel exists: the cost of an
           unscoped skill was measurable and invisible. -->
      {#if data.skills_always_on_chars}
        <p class="banner warn small">
          {fill(t("sk.alwaysOn"), { n: data.skills_always_on_chars })}
        </p>
      {/if}

      {#each skills as skill (skill.name)}
        <article class="row block" class:wide={skill.unscoped}>
          <header>
            <strong>{skill.name}</strong>
            <span class="badge">{skill.scope}</span>
            <span class="badge">{skill.chars} {t("sk.chars")}</span>
            {#if skill.always}
              <!-- Declared, so badged as a statement rather than a warning. -->
              <span class="badge">{t("sk.alwaysDeclared")}</span>
            {:else if skill.unscoped}
              <span class="badge warn">{t("sk.unscoped")}</span>
            {/if}
            {#if skill.truncated}<span class="badge danger">{t("sk.truncated")}</span>{/if}
          </header>
          {#if skill.description}<p class="muted small">{skill.description}</p>{/if}
          <p class="small muted">
            {t("sk.applies")}: {skill.tools?.length ? skill.tools.join(", ") : t("sk.everyTool")}
          </p>
          {#if skill.unknown_tools?.length}
            <!-- A skill naming a tool that does not exist is a skill quietly doing less than its
                 author wrote down — the same "both ends" defect as a playbook naming a missing tool. -->
            <p class="small bad">{fill(t("sk.unknown"), { n: skill.unknown_tools.join(", ") })}</p>
          {/if}

          {#if scoping === skill.name}
            <div class="picker">
              <p class="small muted">{fill(t("sk.scopeHelp"), { n: skill.chars })}</p>
              <div class="tools">
                {#each data.tool_names as tool (tool)}
                  <label class="tool">
                    <input
                      type="checkbox"
                      checked={ticked.includes(tool)}
                      onchange={() => toggle(tool)}
                    />
                    <span>{tool}</span>
                  </label>
                {/each}
              </div>
              <div class="actions">
                <button class="primary" disabled={busy === `scope:${skill.name}`} onclick={() => saveScope(skill.name)}>
                  {t("sk.scopeSave")}
                </button>
                <button class="link" onclick={() => (scoping = "")}>{t("task.cancel")}</button>
              </div>
            </div>
          {:else}
            <div class="actions">
              <button onclick={() => openScope(skill)}>{t("sk.scopeIt")}</button>
              <!-- The path, not an editor. A skill is a file the operator wrote, and this console is
                   not going to be a second, worse text editor for it. -->
              <code class="path small muted" title={skill.path}>{skill.path}</code>
            </div>
          {/if}
        </article>
      {/each}
      {#if skills.length === 0}<p class="empty">{t("sk.none")}</p>{/if}
    {/if}
  </section>
  </div>
{/if}

<style>
  /* Only what Plugins has. The card, the dot field, the rows, the badges and the buttons are the
     console's language and live in `console.css`. */
  h3 { margin: 18px 0 8px; }
  .row.block { display: block; }
  .row.block header { display: flex; gap: 6px; align-items: center; flex-wrap: wrap; }
  /* Scoping a skill: the tool list is long, so it scrolls in its own box rather than pushing the rest
     of the panel off the screen. */
  .picker { margin-top: 10px; }
  .tools {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(190px, 1fr));
    gap: 2px 14px;
    max-height: 220px;
    overflow-y: auto;
    margin: 8px 0 10px;
    padding: 8px;
    border: 1px solid var(--border);
    border-radius: 8px;
  }
  .tool { display: flex; gap: 7px; align-items: center; font-size: 13px; cursor: pointer; }
  .actions { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; margin-top: 8px; }
  .bad { color: var(--danger); }
</style>
