<script>
  /**
   * The first tab rebuilt. What an operator looks at before anything else: what needs them, the
   * pulse, and the run.
   *
   * Three v1 resources, polled separately, which is the whole point of the split. `summary` is
   * 2 859 bytes against the 48 530 the old page fetched every five seconds — and with an `ETag` an
   * unchanged poll transfers **nothing**. `jobs` answers whether the run is still going and, after
   * a restart this client did not witness, that it is `interrupted` rather than silent.
   *
   * `POST /api/v1/approvals` finishes the job: one call into `app_approvals.decide`, which grants
   * the standing rule through the by-name gate *and* releases the work parked on the approval. The
   * old console granted the rule and never released — so an operator approved, the board still read
   * "Held, waiting on you", and nothing moved until a run ticked.
   *
   * Every label here is a key that exists. That is not a courtesy: the first draft of this file
   * invented `hitl.approve`, `ops.needsYou`, `progress.tick` and eight others, none of which are in
   * the table — `t()` would have rendered the key itself on screen. Checked against
   * `web/i18n/en.json` before writing, which is the eleventh time in this restructuring that
   * writing the assertion before reading the product would have shipped something wrong.
   */
  import { get, post, Refused } from "./api.js";
  import { translator } from "./i18n.js";

  // `onTab` is how a card whose call to action is "Open Providers" can actually open it. Optional, so
  // a caller that does not pass it gets a card whose tab buttons do nothing rather than a crash.
  let { lang, company, token = "", onTab = undefined } = $props();
  let t = $derived(translator(lang));

  let summary = $state(null);
  let jobs = $state([]);
  let actions = $state([]);
  // The three that are loaded once rather than polled. `payments` most of all: with a Stripe key set
  // it lists charges over HTTPS, on the operator's own account and rate limit. The shipped page has
  // this right — `loadPayments()` is in its boot sequence and its interval calls `refresh()` alone.
  let payments = $state(null);
  let golive = $state(null);
  let site = $state(null);
  let failure = $state(null);
  let busy = $state("");

  // The old page polled one 48 KB payload at this interval. The interval is unchanged and the
  // payload is 17x smaller, with an ETag making an unchanged one free on the wire.
  const POLL_MS = 5000;

  async function refresh({ first = false } = {}) {
    try {
      // In flight together: separate resources, and none waits on another.
      //
      // `activity` joins the poll **only while a run is going**, plus once on arrival. A log nobody
      // is writing to is a request whose best case is a 304, and the same cadence Operations uses.
      const live = first || summary?.running;
      const wanted = [
        get(`/api/v1/summary?company=${encodeURIComponent(company)}`, { token }),
        get(`/api/v1/jobs?company=${encodeURIComponent(company)}`, { token }),
      ];
      if (live) wanted.push(get(`/api/v1/activity?company=${encodeURIComponent(company)}`, { token }));
      const [s, j, a] = await Promise.all(wanted);
      summary = s;
      jobs = j.jobs ?? [];
      if (a) actions = a.recent_actions ?? [];
      failure = null;
    } catch (e) {
      failure = e instanceof Refused ? e : new Refused(0, { error: { message: String(e) } });
    }
  }

  /** Loaded on arrival and after a write that changes them. Never on the interval. */
  async function loadOnce() {
    const slug = encodeURIComponent(company);
    for (const [key, path] of [
      ["golive", `/api/v1/golive?company=${slug}`],
      ["site", `/api/v1/site?company=${slug}`],
      ["payments", "/api/v1/payments"],
    ]) {
      try {
        const got = await get(path, { token });
        if (key === "golive") golive = got;
        else if (key === "site") site = got;
        else payments = got;
      } catch (e) {
        // One card failing must not take the other two with it. Stripe being unreachable is a normal
        // Tuesday and has its own sentence; a shared banner would blame the console for it.
        if (key === "payments") payments = { error: String(e.message ?? e) };
        else failure = e;
      }
    }
  }

  async function buildSite() {
    busy = "site";
    try {
      await post("/api/v1/site", { company, headline: "" }, { token });
      await loadOnce();
    } catch (e) {
      failure = e;
    } finally {
      busy = "";
    }
  }

  async function publish() {
    busy = "publish";
    try {
      const done = await post("/api/v1/deploy", { company }, { token });
      // Named, because "published" without saying where is a claim an operator cannot check — and
      // because a provider list that all failed is a different answer from nothing being configured.
      // `published`, `provider`, `skipped`, `errors` — there is no `url`. Every provider failing is a
      // different answer from none being configured, and both are different from success, so the
      // three are said apart.
      said = done.provider
        ? `${t("site.published")} ${done.provider}`
        : done.errors?.length
          ? `${t("site.publishFailed")} ${done.errors.join("; ")}`
          : t("site.publishNoProvider");
      await loadOnce();
    } catch (e) {
      failure = e;
    } finally {
      busy = "";
    }
  }

  let said = $state("");
  // Dismissing is a per-browser preference and deliberately not a server field: the card retires
  // itself once the three steps are done, so the worst a new browser costs is seeing a thread that is
  // nearly finished. A settings row for it would be a schema change to remember a shrug.
  let hidden = $state(localStorage.getItem("corparius-onboard-hidden") === "1");

  function hideOnboarding() {
    hidden = true;
    localStorage.setItem("corparius-onboard-hidden", "1");
  }

  $effect(() => {
    refresh({ first: true });
    loadOnce();
    const timer = setInterval(() => refresh(), POLL_MS);
    return () => clearInterval(timer);
  });

  async function decide(id, decision, remember = "") {
    busy = id;
    try {
      const done = await post("/api/v1/approvals", { id, decision, remember }, { token });
      // `gated` is the by-name refusal, and it has to be said out loud: the operator pressed
      // "Approve, stop asking" and the answer to the second half was no, because their own company
      // file names that tool in `hitl_tools`. A button that silently does nothing is worse.
      gated = done.gated ? done.gated : "";
      await refresh();
    } catch (e) {
      failure = e;
    } finally {
      busy = "";
    }
  }

  let gated = $state("");

  async function answer(id) {
    busy = id;
    try {
      await post("/api/v1/inbox", { id, answer: "", company }, { token });
      await refresh();
    } catch (e) {
      failure = e;
    } finally {
      busy = "";
    }
  }

  async function startRun(ticks, loop) {
    busy = "run";
    try {
      // A key per gesture, so a retry over a bad connection cannot start a second run. The core
      // answers the *same* job with `created: false` rather than refusing.
      await post(
        "/api/v1/runs",
        { company, ticks, loop },
        { token, idempotencyKey: `${company}:${ticks}:${loop}:${Date.now()}` },
      );
      await refresh();
    } catch (e) {
      failure = e;
    } finally {
      busy = "";
    }
  }

  async function stopRun() {
    busy = "run";
    try {
      await post("/api/v1/runs/stop", { company }, { token });
      await refresh();
    } catch (e) {
      failure = e;
    } finally {
      busy = "";
    }
  }

  // The thread comes from the server: which step leads is the whole content of an onboarding card, and
  // two clients answering it differently would be two different products.
  let onboarding = $derived(summary?.onboarding ?? []);
  let onboardingDone = $derived(onboarding.length > 0 && onboarding.every((s) => s.done));
  let spend = $derived(summary?.spend_by_agent ?? []);
  // "Not reported" and "free" are different facts. A provider that says nothing about money must
  // never read as costing nothing, which is why `cost_reported` is a separate boolean and not a
  // sum-is-zero check.
  let money = $derived(spend.reduce((total, row) => total + (row.cost ?? 0), 0));
  let needsYou = $derived((summary?.approvals?.length ?? 0) + (summary?.inbox?.length ?? 0));
  let lastRun = $derived(summary?.last_run ?? null);
</script>

{#if failure}
  <p class="banner danger">
    {failure.message}
    {#if failure.code}<code>{failure.code}</code>{/if}
  </p>
{/if}

{#if gated}
  <p class="banner warn">{t("ops.whyGated")} <code>{gated}</code></p>
{/if}

{#if !summary}
  <p class="muted">{t("docs.reading")}</p>
{:else}
  <!-- The thread leads the page until it retires itself, because on an empty install it *is* the page.
       Once the three are done, what needs a person takes over. -->
  {#if onboarding.length && !onboardingDone && !hidden}
    <section class="card">
      <div class="head">
        <div>
          <h2>{t("ob.title")}</h2>
          <p class="desc">{t("ob.desc")}</p>
        </div>
        <button class="link" onclick={hideOnboarding}>{t("ob.dismiss")}</button>
      </div>
      {#each onboarding as step, i (step.key)}
        <div class="step" class:done={step.done} class:lead={step.lead}>
          <span class="mark">{step.done ? "✓" : i + 1}</span>
          <span>
            <strong>{t("ob." + step.key)}</strong>
            <p class="muted small">{t("ob." + step.key + "Hint")}</p>
          </span>
          {#if !step.done}
            <!-- One call to action, on the step the server says leads. Three competing buttons is how
                 a guided thread stops guiding. -->
            <button
              class:quiet={!step.lead}
              disabled={busy === "run"}
              onclick={() => (step.act === "run" ? startRun(24, false) : onTab?.(step.tab))}
            >{t("ob." + step.key + "Cta")}</button>
          {/if}
        </div>
      {/each}
    </section>
  {/if}

  <!-- What needs a person leads the page. The human gate is the subject of this product and should
       not have to be looked for; the old console learned that and put it first too. -->
  <section class="card" class:attention={needsYou > 0}>
    <h2>{t("ops.waiting")} {#if needsYou}<span class="count">{needsYou}</span>{/if}</h2>

    {#each summary.approvals as approval (approval.id)}
      <article class="row">
        <div>
          <strong>{approval.tool}</strong>
          <span class="muted">· {t("ops.requestedBy")} {approval.agent}</span>
          {#if approval.detail?.does}<p class="muted small">{approval.detail.does}</p>{/if}
        </div>
        <div class="actions">
          <button disabled={busy === approval.id} onclick={() => decide(approval.id, "approved")}>
            {t("btn.approve")}
          </button>
          {#if approval.can_remember}
            <button
              class="quiet"
              disabled={busy === approval.id}
              onclick={() => decide(approval.id, "approved", "always")}
            >{t("ops.always")}</button>
          {/if}
          <button
            class="quiet"
            disabled={busy === approval.id}
            onclick={() => decide(approval.id, "rejected")}
          >{t("btn.reject")}</button>
        </div>
      </article>
    {/each}

    {#each summary.inbox as item (item.id)}
      <article class="row">
        <div>
          <strong>{item.title}</strong>
          <span class="muted">· {t("ib." + item.kind)}</span>
          {#if item.body}<p class="muted small">{item.body}</p>{/if}
        </div>
        <div class="actions">
          <button class="quiet" disabled={busy === item.id} onclick={() => answer(item.id)}>
            {t("ib.dismiss")}
          </button>
        </div>
      </article>
    {/each}

    {#if needsYou === 0}<p class="muted">{t("ops.calm")}</p>{/if}
  </section>

  <section class="card">
    <h2>{t("progress.title")}</h2>
    <dl class="pulse">
      <dt>{t("stat.hour")}</dt><dd>{summary.tick}</dd>
      <dt>{t("stat.actions")}</dt><dd>{summary.status.actions.toLocaleString(lang)}</dd>
      <dt>{t("stat.tokens")}</dt>
      <dd>
        {summary.status.tokens.toLocaleString(lang)}
        <span class="muted">/ {summary.session_budget.toLocaleString(lang)}</span>
      </dd>
      <!-- `flow.throughput`, not `done_total`: that one lives in the `tasks` resource and reads
           `null` here. Measured against the live company before wiring it — the twelfth time in
           this restructuring that assuming a field would have shipped a blank number. -->
      <dt>{t("flow.delivered")}</dt><dd>{summary.flow.throughput ?? 0}</dd>
      <dt>{t("flow.wip")}</dt><dd>{summary.flow.wip ?? 0}</dd>
      <dt>{t("stat.waiting")}</dt><dd>{summary.approvals.length}</dd>
    </dl>
    {#if summary.freezes > 0}
      <p class="muted small">{t("badge.frozen")} · {summary.freezes}</p>
    {/if}
  </section>

  <section class="card">
    <h2>{t("run.button")}</h2>
    {#if summary.running}
      <p>
        <span class="state running">{t("badge.running")}</span>
        {#if summary.loop}<span class="muted">· {t("run.loop")}</span>{/if}
        {#if summary.stopping}<span class="muted">· {t("badge.stopping")}</span>{/if}
      </p>
      <button class="quiet" disabled={busy === "run"} onclick={stopRun}>{t("run.stop")}</button>
    {:else}
      <div class="actions">
        <button disabled={busy === "run"} onclick={() => startRun(6, false)} title={t("run.tickTip")}>
          {t("run.h6")}
        </button>
        <button disabled={busy === "run"} onclick={() => startRun(24, false)}>{t("run.h24")}</button>
        <button class="quiet" disabled={busy === "run"} onclick={() => startRun(24, true)}>
          {t("run.loop")}
        </button>
      </div>
    {/if}
    {#if lastRun}
      <!-- An interrupted run says so in its own words, from the core. Nothing was resumed, and
           reporting it as finished would claim ticks that never happened. -->
      <p class="muted small">
        {#if lastRun.error}
          {lastRun.error}
        {:else}
          {t("progress.lastRun")}: {lastRun.ticks_run ?? 0} {t("progress.run")}
        {/if}
      </p>
    {/if}
    {#if jobs.length}
      <ul class="jobs">
        {#each jobs.slice(0, 4) as job (job.id)}
          <li>
            <span class="state {job.state}">{job.state}</span>
            <span class="muted">{job.progress || job.kind}</span>
          </li>
        {/each}
      </ul>
    {/if}
  </section>

  <section class="card">
    <h2>{t("live.title")}</h2>
    <p class="desc">{t("live.desc")}</p>
    {#if golive}
      <dl class="pulse">
        <dt>{t("live.payment")}</dt>
        <dd>{t(golive.payment.wired ? "live.paidOk" : "live.paidNo")}</dd>
        <dt>{t("live.mail")}</dt>
        <dd>{t(golive.mail.wired ? "live.mailOk" : "live.mailNo")}</dd>
        <dt>{t("live.hosting")}</dt>
        <dd>
          <!-- Three states, not two: not hosted, a token set but nothing published yet, and live at a
               URL. Collapsing the middle one would tell an operator who has done half the work that
               they have done none of it. -->
          {#if golive.hosting.published_url}
            {t("live.hostLive")}
            <a href={golive.hosting.published_url} target="_blank" rel="noreferrer noopener">
              {golive.hosting.published_url}
            </a>
          {:else if golive.hosting.token_set}
            {t("live.hostReady")}
          {:else}
            {t("live.hostNo")}
          {/if}
        </dd>
      </dl>
    {/if}
  </section>

  <section class="card">
    <h2>{t("site.title")}</h2>
    <p class="desc">{t("site.desc")}</p>
    {#if site}
      {#if site.built}
        <p class="small muted">
          {new Date(site.mtime * 1000).toLocaleString(lang)}
          <!-- Which site this is. The console once previewed the generated path while the terminal
               published the owned one, and both reported success — the second live divergence this
               restructuring found. -->
          {#if site.owned}· <code>{site.pages.length} {t("site.title")}</code>{/if}
        </p>
      {:else}
        <p class="muted">{t("site.none")}</p>
      {/if}
      <div class="actions">
        <button disabled={busy === "site"} onclick={buildSite}>
          {t(site.built ? "site.regenerate" : "site.generate")}
        </button>
        {#if site.built}
          <button class="quiet" disabled={busy === "publish"} onclick={publish}>
            {busy === "publish" ? t("site.publishing") : t("site.publish")}
          </button>
        {/if}
      </div>
      {#if said}<p class="small muted">{said}</p>{/if}
    {/if}
  </section>

  <section class="card">
    <h2>{t("pay.title")}</h2>
    <p class="desc">{t("pay.desc")}</p>
    {#if payments?.error}
      <p class="small muted">{t("pay.error")} {payments.error}</p>
    {:else if payments}
      <!-- `source` is "stripe", "mock" or "error" — never "live", which was my invention and would
           have labelled real charges as samples. Sample data reading as sales is the worst kind of
           wrong on the one card about money, so the mock says so and an error says which. -->
      {#if payments.source === "mock"}<p class="small muted">{t("pay.mock")}</p>{/if}
      {#if payments.source === "error"}<p class="small muted">{t("pay.error")} {payments.error}</p>{/if}
      {#if payments.payments.length === 0}
        <p class="muted">{t("pay.none")}</p>
      {:else}
        <dl class="pulse">
          <dt>{t("pay.total")}</dt><dd>{payments.total_paid.toFixed(2)}</dd>
        </dl>
        <ul class="feed">
          {#each payments.payments.slice(0, 6) as charge, i (charge.ts + ":" + i)}
            <li>
              <strong>{charge.amount.toFixed(2)} {charge.currency}</strong>
              <span class="muted">{charge.description}</span>
              {#if !charge.paid}<span class="state bad">{t("badge.fail")}</span>{/if}
            </li>
          {/each}
        </ul>
      {/if}
    {/if}
  </section>

  <section class="card">
    <h2>{t("spend.title")}</h2>
    <p class="desc">{t("spend.desc")}</p>
    {#if spend.length === 0}
      <p class="muted">{t("spend.empty")}</p>
    {:else}
      <dl class="pulse">
        {#each spend as row (row.agent)}
          <dt>{row.agent}</dt>
          <dd>
            {row.t.toLocaleString(lang)} <span class="muted">{t("progress.tokens")}</span>
            {#if row.cost}· {row.cost.toFixed(4)}{/if}
          </dd>
        {/each}
      </dl>
      <!-- A total of 0.00 and "nobody reported a cost" are different facts, and `cost_reported` is
           what separates them. Telling an operator on a paid key that they spent nothing would be the
           worst kind of wrong: quietly plausible. -->
      {#if summary.cost_reported}
        <p class="small muted">{money.toFixed(4)}</p>
      {:else}
        <p class="small muted">{t("spend.noCost")}</p>
      {/if}
    {/if}
  </section>

  <section class="card">
    <h2>{t("activity.title")}</h2>
    <p class="desc">{t("activity.desc")}</p>
    {#if actions.length === 0}
      <p class="muted">{t("activity.empty")}</p>
    {:else}
      <ul class="feed">
        {#each actions.slice(0, 8) as action, i (action.ts + ":" + i)}
          <li>
            <span class="state {action.ok ? 'ok' : 'bad'}">{t(action.ok ? "badge.ok" : "badge.fail")}</span>
            <strong>{action.tool}</strong>
            <span class="muted">{action.agent}</span>
            <!-- Which provider answered, and whether the chain fell back. Schema 18 exists because
                 this was produced and thrown away: an operator read "Nothing usable drafted" as a
                 broken site generator while two providers were answering 429, after 365 026 tokens. -->
            {#if action.source}<span class="muted small">{action.source}</span>{/if}
            {#if action.fell_back}<span class="count">{t("tier.chain")}</span>{/if}
          </li>
        {/each}
      </ul>
      <p class="muted small">{t("activity.openLog")}</p>
    {/if}
  </section>
{/if}

<style>
  /* Tokens only — no colour is written here. `tokens.css` carries the measured oklch ramps ported
     verbatim from the shipped page, including the one that shipped at 1.16:1. */
  .card {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 1rem 1.1rem;
    margin: 0 0 1rem;
  }
  .card.attention { border-color: var(--warn); }
  h2 {
    font-size: 0.82rem;
    text-transform: uppercase;
    letter-spacing: 0.07em;
    color: var(--muted);
    margin: 0 0 0.8rem;
  }
  .count {
    background: var(--warn-soft);
    color: var(--warn);
    border-radius: 999px;
    padding: 0 0.45rem;
    margin-left: 0.3rem;
  }
  .row {
    display: flex;
    gap: 1rem;
    justify-content: space-between;
    align-items: flex-start;
    padding: 0.65rem 0;
    border-top: 1px solid var(--border);
  }
  .row:first-of-type { border-top: 0; padding-top: 0; }
  .actions { display: flex; gap: 0.4rem; flex-wrap: wrap; }
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
  button:disabled { opacity: 0.45; cursor: default; }
  button:focus-visible { outline: 2px solid var(--select); outline-offset: 2px; }
  .muted { color: var(--muted); }
  .small { font-size: 0.88rem; margin: 0.3rem 0 0; }
  .banner { padding: 0.6rem 0.85rem; border-radius: 8px; margin: 0 0 1rem; border: 1px solid; }
  .banner.danger { border-color: var(--danger); background: var(--danger-soft); color: var(--danger); }
  .banner.warn { border-color: var(--warn); background: var(--warn-soft); color: var(--warn); }
  .pulse { display: grid; grid-template-columns: auto 1fr; gap: 0.3rem 1.4rem; margin: 0; }
  dt { color: var(--muted); }
  dd { margin: 0; font-variant-numeric: tabular-nums; }
  .step {
    display: grid;
    grid-template-columns: 1.6rem 1fr auto;
    gap: 0.6rem;
    align-items: start;
    padding: 0.5rem 0;
    border-top: 1px solid var(--border);
  }
  .step:first-of-type { border-top: 0; }
  .step p { margin: 0.15rem 0 0; }
  .mark {
    display: grid;
    place-items: center;
    width: 1.5rem;
    height: 1.5rem;
    border-radius: 999px;
    border: 1px solid var(--border-ui);
    color: var(--muted);
    font-size: 0.8rem;
  }
  /* Done is settled, leading is the one to do now, the rest wait. Three states because a thread with
     two cannot say which of the unfinished steps is next. */
  .step.done .mark { color: var(--ok); border-color: var(--ok); }
  .step.done strong { color: var(--muted); }
  .step.lead .mark { color: var(--accent); border-color: var(--accent); }
  .head { display: flex; gap: 1rem; justify-content: space-between; align-items: flex-start; }
  .jobs, .feed { list-style: none; padding: 0; margin: 0.8rem 0 0; display: grid; gap: 0.3rem; font-size: 0.88rem; }
  .feed li { display: flex; gap: 0.4rem; align-items: baseline; flex-wrap: wrap; }
  .state { font-variant-numeric: tabular-nums; color: var(--muted); }
  .state.running { color: var(--ok); }
  .state.interrupted, .state.failed { color: var(--danger); }
</style>
