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

  let { lang, company, token = "" } = $props();
  let t = $derived(translator(lang));

  let summary = $state(null);
  let jobs = $state([]);
  let failure = $state(null);
  let busy = $state("");

  // The old page polled one 48 KB payload at this interval. The interval is unchanged and the
  // payload is 17x smaller, with an ETag making an unchanged one free on the wire.
  const POLL_MS = 5000;

  async function refresh() {
    try {
      // Both in flight at once: they are separate resources and neither waits on the other.
      const [s, j] = await Promise.all([
        get(`/api/v1/summary?company=${encodeURIComponent(company)}`, { token }),
        get(`/api/v1/jobs?company=${encodeURIComponent(company)}`, { token }),
      ]);
      summary = s;
      jobs = j.jobs ?? [];
      failure = null;
    } catch (e) {
      failure = e instanceof Refused ? e : new Refused(0, { error: { message: String(e) } });
    }
  }

  $effect(() => {
    refresh();
    const timer = setInterval(refresh, POLL_MS);
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
  .jobs { list-style: none; padding: 0; margin: 0.8rem 0 0; display: grid; gap: 0.3rem; font-size: 0.88rem; }
  .state { font-variant-numeric: tabular-nums; color: var(--muted); }
  .state.running { color: var(--ok); }
  .state.interrupted, .state.failed { color: var(--danger); }
</style>
