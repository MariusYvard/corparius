<script>
  /**
   * The fourth tab: which model answers, and what it costs to find out.
   *
   * ## Every probe is a button, and that is the organising rule
   *
   * The reads here are filesystem checks and stored settings. Nothing on this tab opens a socket
   * until an operator presses something — a rule written after `/api/providers` opened one on every
   * refresh, and the reason `providers` reports `claude_installed` from disk and omits the Claude
   * tier plan entirely: building that plan needs to know whether Ollama answers, which on a machine
   * without it is a connect timeout per poll.
   *
   * So `probe`, `models`, `preflight` and `claude/setup` are POSTs. Each spends a real request on the
   * operator's own account, and the verb says so.
   *
   * ## Keys are write-only
   *
   * `key_set` is a boolean and the value never comes back. A payload that echoed a credential would
   * put it in every client's cache and every proxy log, so the field shows a placeholder and an empty
   * submission means *revoke* — which is stored as an empty string rather than cleared, because a
   * cleared row lets `.env` show through and the key would come back. Measured, and the reason
   * `app_settings.CREDENTIALS` exists.
   *
   * ## The two long operations, and the only place this tab polls
   *
   * The Ollama pull and the preflight sweep are **durable jobs** now, not `UiState` dicts — so a
   * restart reports `interrupted` rather than forgetting, and a phone can watch one this console
   * started. `GET /api/v1/machine` is the read, and it is polled **only while one is running**: a poll
   * against no work is a round trip whose best case is nothing changed.
   *
   * The sweep asks before it spends. `{estimate: true}` answers how many calls it would make without
   * making any, and that number goes in front of the operator first — NVIDIA alone advertises 102
   * models, and "check everything" is their money and their rate limits.
   */
  import { get, post, Refused } from "./api.js";
  import { fill, translator } from "./i18n.js";

  let { lang, token = "" } = $props();
  let t = $derived(translator(lang));

  let providers = $state(null);
  let ollama = $state(null);
  let claude = $state(null);
  let failure = $state(null);
  let busy = $state("");
  let said = $state("");

  // Per-provider: the key being typed, the catalogue that was fetched, the last probe result.
  let typed = $state({});
  let models = $state({});
  let probed = $state({});
  let tiers = $state({});
  let report = $state(null);
  let setup = $state(null);
  let estimate = $state(null);

  // The one interval on this tab, and it exists only while work does. `POLL_MS` matches the rest of
  // the console; a pull is gigabytes and a sweep is minutes, so five seconds is not a busy loop.
  const POLL_MS = 5000;

  async function load() {
    try {
      const [p, o, c] = await Promise.all([
        get("/api/v1/providers", { token }),
        get("/api/v1/ollama", { token }),
        get("/api/v1/claude", { token }),
      ]);
      providers = p;
      ollama = o;
      claude = c;
      // Only from the server's own view, and only when the operator is not mid-edit: these are text
      // fields, and clobbering what somebody is typing on a refresh is its own small betrayal.
      if (!Object.keys(tiers).length) tiers = { ...p.tiers };
      failure = null;
    } catch (e) {
      failure = e instanceof Refused ? e : new Refused(0, { error: { message: String(e) } });
    }
  }

  async function loadSetup() {
    try {
      setup = await get("/api/v1/machine", { token });
    } catch (e) {
      failure = e instanceof Refused ? e : new Refused(0, { error: { message: String(e) } });
    }
  }

  // Loaded, not polled — except while a job is live. `busyJob` is what turns the interval on, so a
  // tab sitting on a finished pull makes no requests at all.
  $effect(() => {
    load();
    loadSetup();
  });

  $effect(() => {
    if (!busyJob) return;
    const timer = setInterval(loadSetup, POLL_MS);
    return () => clearInterval(timer);
  });

  async function save(key, values, toast = "") {
    busy = key;
    said = "";
    try {
      const done = await post("/api/v1/providers", { values }, { token });
      providers = done;
      said = toast || t("toast.saved");
      // A bootstrap key lands in .env and only applies after a restart. Saying so is the difference
      // between a setting that looks ignored and one that is waiting.
      if (done.restart_required?.length) said = `${said} — restart: ${done.restart_required.join(", ")}`;
      if (done.shadowed?.length) said = `${said} — shadowed by the environment: ${done.shadowed.join(", ")}`;
      return done;
    } catch (e) {
      failure = e;
      return null;
    } finally {
      busy = "";
    }
  }

  const saveKey = (p) => save(p.name, { [p.key_env]: typed[p.name] ?? "" }, t("toast.keySaved"));

  const toggle = (env, on) => save(env, { [env]: on ? "true" : "false" });

  const saveTiers = () =>
    save(
      "tiers",
      {
        CORP_TRIVIAL_MODEL: tiers.trivial ?? "",
        CORP_NORMAL_MODEL: tiers.normal ?? "",
        CORP_HARD_MODEL: tiers.hard ?? "",
        CORP_LOCAL_MODEL: tiers.local_fallback ?? "",
        CORP_LLM_FALLBACK: tiers.fallback_chain ?? "",
      },
      t("toast.tiersSaved"),
    );

  async function recommend() {
    busy = "routing";
    said = "";
    try {
      const done = await post("/api/v1/tiers/recommend", {}, { token });
      providers = done;
      tiers = { ...done.tiers };
      said = t("toast.routed");
    } catch (e) {
      failure = e;
    } finally {
      busy = "";
    }
  }

  async function probe(name) {
    busy = `probe:${name}`;
    try {
      const done = await post("/api/v1/providers/probe", { name }, { token });
      probed[name] = done.result;
    } catch (e) {
      failure = e;
    } finally {
      busy = "";
    }
  }

  async function listModels(name) {
    busy = `models:${name}`;
    try {
      const done = await post("/api/v1/providers/models", { name }, { token });
      models[name] = done;
      // `ok: false` here is a provider that did not answer, not a request that was wrong — and it
      // still carries what a preflight proved, so the list is useful either way.
      said = done.ok
        ? fill(t("prov.modelsLoaded"), { n: done.models.length })
        : done.error;
    } catch (e) {
      failure = e;
    } finally {
      busy = "";
    }
  }

  async function runPreflight() {
    busy = "preflight";
    said = "";
    try {
      report = await post("/api/v1/preflight", {}, { token });
    } catch (e) {
      failure = e;
      report = null;
    } finally {
      busy = "";
    }
  }

  async function useClaude(allTiers) {
    busy = "claude";
    said = "";
    try {
      const done = await post("/api/v1/claude/setup", { all_tiers: allTiers }, { token });
      providers = done;
      tiers = { ...done.tiers };
      said = t("cc.done");
      claude = await get("/api/v1/claude", { token });
    } catch (e) {
      failure = e;
    } finally {
      busy = "";
    }
  }

  async function pull() {
    busy = "pull";
    said = "";
    try {
      await post("/api/v1/ollama/pull", { models: [] }, { token });
      said = t("oll.starting");
      await loadSetup();
    } catch (e) {
      failure = e;
    } finally {
      busy = "";
    }
  }

  async function priceSweep() {
    busy = "sweep";
    try {
      estimate = await post("/api/v1/preflight/sweep", { estimate: true }, { token });
    } catch (e) {
      failure = e;
    } finally {
      busy = "";
    }
  }

  async function startSweep() {
    busy = "sweep";
    estimate = null;
    try {
      await post("/api/v1/preflight/sweep", {}, { token });
      await loadSetup();
    } catch (e) {
      failure = e;
    } finally {
      busy = "";
    }
  }

  async function stopJob(path) {
    busy = "stop";
    try {
      await post(path, { stop: true }, { token });
      await loadSetup();
    } catch (e) {
      failure = e;
    } finally {
      busy = "";
    }
  }

  let pullJob = $derived(setup?.pull ?? {});
  let sweepJob = $derived(setup?.sweep ?? {});
  let busyJob = $derived(pullJob.state === "running" || sweepJob.state === "running");
  let connected = $derived((providers?.providers ?? []).filter((p) => p.configured));
  let mockOn = $derived(Boolean(providers?.llm_mock));
  let cloudOff = $derived(providers && !providers.cloud_enabled);
</script>

{#if failure}
  <p class="banner danger">
    {failure.message}
    {#if failure.code}<code>{failure.code}</code>{/if}
  </p>
{/if}
{#if said}<p class="banner ok">{said}</p>{/if}

{#if !providers}
  <p class="muted">{t("docs.reading")}</p>
{:else}
  <!-- The two gates that make a saved key do nothing, said before the key fields rather than after:
       an operator who pastes a key into a console in mock mode has done everything right and nothing
       will happen. -->
  {#if mockOn}<p class="banner warn">{t("prov.stillMock")}</p>{/if}
  {#if cloudOff}<p class="banner warn">{t("prov.cloudOff")}</p>{/if}

  <section class="card">
    <h2>{t("cc.title")}</h2>
    <p class="desc">{t("cc.desc")}</p>
    {#if claude}
      <p>
        <span class="chip" class:ok={claude.installed}>
          {t(claude.installed ? "cc.found" : "cc.missing")}
        </span>
        {#if claude.ready}<span class="chip ok">{t("cc.on")}</span>{/if}
      </p>
      {#if !claude.installed}
        <!-- The single most common confusion in this setup, and it costs nothing to answer from the
             filesystem: the chat app is not the CLI. -->
        {#if claude.desktop}<p class="muted small">{t("cc.desktop")}</p>{/if}
        <p class="muted small">{t("cc.step1")} <code>{claude.install_cmd}</code></p>
      {:else}
        <p class="muted small">
          {#if connected.length}
            {fill(t("cc.mixed"), { n: connected.length })}
          {:else}
            {t("cc.everyTier")}
          {/if}
        </p>
        <div class="actions">
          <button disabled={busy === "claude"} onclick={() => useClaude(false)}>
            {busy === "claude" ? t("cc.applying") : t(claude.ready ? "cc.reapply" : "cc.use")}
          </button>
          <button class="quiet" disabled={busy === "claude"} onclick={() => useClaude(true)}>
            {t("cc.useAll")}
          </button>
        </div>
      {/if}
    {/if}
  </section>

  <section class="card">
    <h2>{t("prov.runtime")}</h2>
    <p class="desc">{t("prov.note")}</p>
    <label class="row toggle">
      <span><strong>{t("prov.mock")}</strong> <span class="muted">· {t("prov.mockHint")}</span></span>
      <input
        type="checkbox"
        checked={providers.llm_mock}
        disabled={busy === "CORP_LLM_MOCK"}
        onchange={(e) => toggle("CORP_LLM_MOCK", e.currentTarget.checked)}
      />
    </label>
    <label class="row toggle">
      <span><strong>{t("prov.cloud")}</strong> <span class="muted">· {t("prov.cloudHint")}</span></span>
      <input
        type="checkbox"
        checked={providers.cloud_enabled}
        disabled={busy === "CORP_CLOUD_ENABLED"}
        onchange={(e) => toggle("CORP_CLOUD_ENABLED", e.currentTarget.checked)}
      />
    </label>
    <label class="row toggle">
      <span><strong>{t("prov.cc")}</strong> <span class="muted">· {t("prov.ccHint")}</span></span>
      <input
        type="checkbox"
        checked={providers.claude_code}
        disabled={busy === "CORP_CLAUDE_CODE"}
        onchange={(e) => toggle("CORP_CLAUDE_CODE", e.currentTarget.checked)}
      />
    </label>
  </section>

  <section class="card">
    <h2>{t("prov.free")}</h2>
    <p class="desc">{t("prov.freeNote")}</p>

    {#each providers.providers as p (p.name)}
      <article class="row block">
        <header>
          <strong>{p.name}</strong>
          {#if p.recommended}<span class="chip ok">{t("prov.startHere")}</span>{/if}
          {#if p.no_card}<span class="chip" title={t("prov.noCardTip")}>{t("prov.noCard")}</span>{/if}
          {#if p.key_optional}<span class="chip">{t("prov.optional")}</span>{/if}
          <span class="chip" class:ok={p.configured}>
            {t(p.key_set ? "badge.keySet" : "badge.noKey")}
          </span>
        </header>

        <div class="key">
          <input
            type="password"
            autocomplete="off"
            placeholder={p.key_set ? "••••••••" : t("prov.paste")}
            value={typed[p.name] ?? ""}
            oninput={(e) => (typed[p.name] = e.currentTarget.value)}
          />
          <button disabled={busy === p.name} onclick={() => saveKey(p)}>{t("btn.save")}</button>
          <button class="quiet" disabled={busy === `probe:${p.name}`} onclick={() => probe(p.name)}>
            {busy === `probe:${p.name}` ? t("prov.testing") : t("prov.test")}
          </button>
          <button
            class="quiet"
            disabled={busy === `models:${p.name}`}
            onclick={() => listModels(p.name)}
          >
            {busy === `models:${p.name}` ? t("prov.loadingModels") : t("prov.models")}
          </button>
          {#if p.signup}
            <a class="link" href={p.signup} target="_blank" rel="noreferrer noopener">
              {t("prov.getKey")}
            </a>
          {/if}
        </div>

        {#if probed[p.name]}
          <p class="small" class:good={probed[p.name].ok} class:bad={!probed[p.name].ok}>
            {probed[p.name].detail}
          </p>
        {/if}

        {#if models[p.name]}
          <!-- The proven set is the part that was measured rather than claimed: 10 of 18 NVIDIA
               catalogue entries answered 404 with a real key, so an unmarked catalogue is a coin
               flip. Proven models are named first and marked. -->
          <p class="small muted">
            {#each models[p.name].models.slice(0, 24) as m (m)}
              <button
                class="model"
                class:proved={models[p.name].proved?.[m] === "usable"}
                onclick={() => (tiers.normal = m)}
                title={models[p.name].proved?.[m] ?? ""}
              >{m}</button>
            {/each}
          </p>
        {/if}
      </article>
    {/each}
  </section>

  <section class="card">
    <h2>{t("prov.tiers")}</h2>
    <p class="desc">{t("prov.format")}</p>
    <p class="muted small">{t("prov.routingNote")}</p>
    <div class="actions">
      <button disabled={busy === "routing"} onclick={recommend}>{t("prov.useRouting")}</button>
    </div>
    <div class="grid">
      {#each [["trivial", "tier.trivial"], ["normal", "tier.normal"], ["hard", "tier.hard"], ["local_fallback", "tier.local"], ["fallback_chain", "tier.chain"]] as [field, label] (field)}
        <label>
          <span class="muted">{t(label)}</span>
          <input
            value={tiers[field] ?? ""}
            oninput={(e) => (tiers[field] = e.currentTarget.value)}
          />
        </label>
      {/each}
    </div>
    <div class="actions">
      <button disabled={busy === "tiers"} onclick={saveTiers}>{t("prov.saveTiers")}</button>
      <button class="quiet" disabled={busy === "preflight" || mockOn} onclick={runPreflight}>
        {busy === "preflight" ? t("prov.preflightRunning") : t("prov.preflight")}
      </button>
    </div>

    {#if report}
      <div class="report">
        {#each report.probes ?? [] as row, i (row.tier + ":" + i)}
          <p class="small">
            <span class="chip {row.state}">{t("prov.pf." + row.state)}</span>
            <strong>{row.tier}</strong> <span class="muted">{row.model}</span>
            {#if row.detail}<span class="muted">— {row.detail}</span>{/if}
          </p>
        {/each}
        <!-- What a preflight cannot reach, named rather than dropped: one that covers three of six
             tiers and reports success is worse than one that admits its reach. -->
        {#each report.skipped ?? [] as row, i (row.tier + ":" + i)}
          <p class="small muted">
            <span class="chip">{t("prov.pf.skipped")}</span>
            <strong>{row.tier}</strong> {row.model} — {t("prov.probeSkipReason")}
          </p>
        {/each}
        {#if (report.probes ?? []).length === 0 && (report.skipped ?? []).length === 0}
          <p class="small muted">{t("prov.probeNoTier")}</p>
        {/if}
      </div>
    {/if}

    <!-- The full sweep, and it asks before it spends. `estimate` is a real answer from the server
         (`{estimate: true}` makes no calls), so the number in front of the operator is measured
         rather than guessed. NVIDIA alone advertises 102 models. -->
    <div class="actions">
      {#if sweepJob.state === "running"}
        <span class="chip warn">{t("badge.running")}</span>
        <span class="small muted">{sweepJob.progress}</span>
        <button class="quiet" disabled={busy === "stop"} onclick={() => stopJob("/api/v1/preflight/sweep")}>
          {t("prov.sweepStop")}
        </button>
      {:else if estimate}
        <p class="small">
          {fill(t("prov.sweepConfirm"), {
            n: estimate.total ?? 0,
            p: Object.keys(estimate.providers ?? {}).length,
          })}
        </p>
        <button disabled={busy === "sweep"} onclick={startSweep}>{t("prov.sweepAll")}</button>
        <button class="link" onclick={() => (estimate = null)}>{t("task.cancel")}</button>
      {:else}
        <button class="quiet" disabled={busy === "sweep" || mockOn} onclick={priceSweep}>
          {t("prov.sweepAll")}
        </button>
      {/if}
    </div>

    {#if setup}
      <p class="small muted">
        {fill(t("prov.sweepDone"), { n: setup.known ?? 0 })}
        {#each Object.entries(setup.usable_by_provider ?? {}) as [name, count] (name)}
          <span class="chip">{name} {count}</span>
        {/each}
      </p>
      <!-- A verdict is a measurement and measurements age. Said out loud so nobody reads a
           six-month-old `blocked` as current fact. -->
      {#if setup.worth_rechecking}
        <p class="small muted">{setup.worth_rechecking} · {setup.oldest_days}d</p>
      {/if}
      <!-- `interrupted` is a state a client really sees: a console killed mid-sweep leaves a row the
           next process marks on startup. Nothing was resumed, and saying so beats both silence and a
           silent restart of hundreds of paid calls. -->
      {#if sweepJob.state && sweepJob.state !== "running"}
        <p class="small muted"><span class="chip {sweepJob.state}">{sweepJob.state}</span> {sweepJob.progress}</p>
      {/if}
    {/if}
  </section>

  <section class="card">
    <h2>{t("oll.title")}</h2>
    <p class="desc">{t("oll.desc")}</p>
    {#if ollama}
      <p>
        <span class="chip" class:ok={ollama.reachable}>{t(ollama.reachable ? "oll.ready" : "oll.off")}</span>
        {#if ollama.missing?.length}
          <span class="chip warn">{t("oll.partial")}</span>
        {:else if ollama.reachable}
          <span class="muted small">{t("oll.allSet")}</span>
        {/if}
      </p>
      {#if !ollama.reachable}<p class="muted small">{t("oll.install")} <code>ollama.com</code></p>{/if}
      {#if ollama.missing?.length}
        <p class="muted small">{t("oll.missing")} {ollama.missing.join(", ")}</p>
        <div class="actions">
          {#if pullJob.state === "running"}
            <span class="chip warn">{t("oll.pulling")}</span>
            <button class="quiet" disabled={busy === "stop"} onclick={() => stopJob("/api/v1/ollama/pull/stop")}>
              {t("run.stop")}
            </button>
          {:else}
            <button disabled={busy === "pull"} onclick={pull}>{t("oll.pull")}</button>
          {/if}
        </div>
      {/if}
      {#if pullJob.state}
        <!-- The progress line is the row's own column, so this is what a phone reads too — and what
             survives the console being restarted mid-download. -->
        <p class="small muted">
          <span class="chip {pullJob.state}">{pullJob.state}</span>
          {pullJob.progress || ""}
          {#if pullJob.result?.done?.length}· {t("oll.done")}{/if}
        </p>
      {/if}
      <!-- Reachable is not capable. The measurement decides whether local may carry a tier, and its
           absence is stated rather than assumed away. -->
      {#if ollama.machine?.tokens_per_second}
        <p class="muted small">
          {fill(t("oll.measured"), {
            c: ollama.machine.cores ?? "?",
            s: Math.round(ollama.machine.tokens_per_second),
            p: ollama.machine.placement ?? "",
          })}
        </p>
      {:else}
        <p class="muted small">{t("oll.unmeasured")}</p>
      {/if}
      <!-- `recommended_local` answers ("", reason) when local should serve nothing, and `reason` is
           a sentence rather than a code — so the branch is on whether a model was chosen, and the
           sentence is printed as written. Reading it as an enum was the fifth wrong guess here. -->
      {#if ollama.local_model}
        <p class="muted small">
          {t("oll.serves")} <code>{ollama.local_model}</code>
        </p>
      {:else if ollama.local_reason}
        <p class="muted small">{t("oll.fallbackOnly")} {ollama.local_reason}</p>
      {/if}
    {/if}
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
  h2 {
    font-size: 0.82rem;
    text-transform: uppercase;
    letter-spacing: 0.07em;
    color: var(--muted);
    margin: 0 0 0.35rem;
  }
  .desc { color: var(--muted); font-size: 0.9rem; margin: 0 0 0.9rem; }
  .row {
    display: flex;
    gap: 1rem;
    justify-content: space-between;
    align-items: flex-start;
    padding: 0.6rem 0;
    border-top: 1px solid var(--border);
  }
  .row:first-of-type { border-top: 0; }
  .row.block { display: block; }
  .row.block header { display: flex; gap: 0.4rem; align-items: center; flex-wrap: wrap; }
  .row.toggle { align-items: center; cursor: pointer; }
  .key { display: flex; gap: 0.4rem; flex-wrap: wrap; align-items: center; margin-top: 0.45rem; }
  .key input { flex: 1 1 12rem; }
  .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(15rem, 1fr)); gap: 0.6rem; margin: 0.8rem 0; }
  .grid label { display: grid; gap: 0.2rem; font-size: 0.88rem; }
  .actions { display: flex; gap: 0.4rem; flex-wrap: wrap; align-items: center; margin-top: 0.5rem; }
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
  button.model {
    background: var(--raised);
    color: var(--muted);
    border-color: var(--border);
    border-radius: 999px;
    padding: 0.1rem 0.55rem;
    font-size: 0.8rem;
    margin: 0.15rem 0.15rem 0 0;
  }
  button.model.proved { color: var(--ok); border-color: var(--ok); }
  button:disabled { opacity: 0.45; cursor: default; }
  button:focus-visible, input:focus-visible, a:focus-visible {
    outline: 2px solid var(--select);
    outline-offset: 2px;
  }
  input {
    background: var(--raised);
    color: var(--text);
    border: 1px solid var(--border-ui);
    border-radius: 6px;
    padding: 0.3rem 0.5rem;
    font: inherit;
  }
  input[type="checkbox"] { width: auto; }
  a.link { color: var(--accent); font-size: 0.88rem; }
  .muted { color: var(--muted); }
  .small { font-size: 0.86rem; margin: 0.35rem 0 0; }
  .good { color: var(--ok); }
  .bad { color: var(--danger); }
  .banner { padding: 0.6rem 0.85rem; border-radius: 8px; margin: 0 0 1rem; border: 1px solid; }
  .banner.danger { border-color: var(--danger); background: var(--danger-soft); color: var(--danger); }
  .banner.warn { border-color: var(--warn); background: var(--warn-soft); color: var(--warn); }
  .banner.ok { border-color: var(--ok); background: var(--ok-soft); color: var(--ok); }
  .chip {
    background: var(--raised);
    border: 1px solid var(--border-ui);
    border-radius: 999px;
    padding: 0 0.5rem;
    font-size: 0.78rem;
    color: var(--muted);
  }
  .chip.ok { color: var(--ok); border-color: var(--ok); }
  .chip.warn { color: var(--warn); border-color: var(--warn); }
  /* The probe legend, and the ramp carries the meaning: blocked is a key that will not work,
     capacity is one that will later, usable is measured. */
  .chip.blocked { color: var(--danger); border-color: var(--danger); }
  .chip.capacity { color: var(--warn); border-color: var(--warn); }
  .chip.usable { color: var(--ok); border-color: var(--ok); }
  .report { margin-top: 0.7rem; border-top: 1px solid var(--border); padding-top: 0.5rem; }
</style>
