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
  import { fill, translator } from "./i18n.js";
  import Empty from "./Empty.svelte";
  import AgentIcon from "./AgentIcon.svelte";
  import Approval from "./Approval.svelte";

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
  // The bars need a scale, and it is the busiest agent rather than the budget: a role that used
  // 2% of a session budget draws no bar at all, which says nothing about who is doing the work.
  let busiest = $derived(Math.max(1, ...spend.map((row) => row.t ?? 0)));
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
      <div class="card-head">
        <div>
          <h2>{t("ob.title")}</h2>
          <p class="desc">{t("ob.desc")}</p>
        </div>
        <button class="link" onclick={hideOnboarding}>{t("ob.dismiss")}</button>
      </div>
      <div>
        {#each onboarding as step, i (step.key)}
          <div class="ob-step" class:done={step.done} class:now={step.lead}>
            <span class="ob-mark">{step.done ? "✓" : i + 1}</span>
            <span>
              <strong>{t("ob." + step.key)}</strong>
              <p class="desc">{t("ob." + step.key + "Hint")}</p>
            </span>
            {#if !step.done}
              <!-- One call to action, on the step the server says leads. Three competing buttons is
                   how a guided thread stops guiding. -->
              <button
                class={step.lead ? "primary" : ""}
                disabled={busy === "run"}
                onclick={() => (step.act === "run" ? startRun(24, false) : onTab?.(step.tab))}
              >{t("ob." + step.key + "Cta")}</button>
            {/if}
          </div>
        {/each}
      </div>
    </section>
  {/if}

  <!-- Decisions first, above the day.
       A review counted this page saying "you have 2 decisions" three times, in three stacked cards
       of near-equal weight: the onboarding step, the gate's own number, and then the requests
       themselves — so the product's whole reason to exist was the third-most prominent thing on its
       home page. The requests lead now, and the gate below speaks only when there is nothing to
       decide, which is the one case where a count is news. -->
  {#if needsYou > 0}
    <section class="card attention">
      <div class="card-head">
        <div>
          <h2>{t("ops.waiting")} <span class="badge warm">{needsYou}</span></h2>
          <p class="desc">{t("ops.waitingDesc")}</p>
        </div>
      </div>
      <div class="rows">
        <!-- One component, two instances. The short form was dropping the risk chip — the only
             thing that tells a spend from a read — so the surface an operator meets first could
             not say whether Approve sends an email or reads a file. `Approval.svelte` carries the
             reasoning. -->
        {#each summary.approvals as approval (approval.id)}
          <Approval {approval} {lang} {busy} compact onDecide={decide} />
        {/each}

        {#each summary.inbox as item (item.id)}
          <article class="row">
            <div class="grow">
              <strong>{item.title}</strong>
              <span class="muted small">· {t("ib." + item.kind)}</span>
              {#if item.body}<p class="desc">{item.body}</p>{/if}
            </div>
            <div class="actions">
              <button disabled={busy === item.id} onclick={() => answer(item.id)}>
                {t("ib.dismiss")}
              </button>
            </div>
          </article>
        {/each}
      </div>
    </section>
  {/if}

  <!-- The status band. The human gate is the subject of this product and sits in display scale on the
       left; the day's numbers read across from it. One band with presence, rather than the two
       equal-weight cards this page had, where "0 waiting" and "253 simulated hours" were the same
       size and neither was the answer to "does this need me". -->
  <section class="card hero" class:is-running={summary.running} class:no-gate={needsYou > 0}>
    <!-- The gate speaks when there is nothing waiting. When something is, the requests are already
         open above it and a second card counting them is the third telling of one fact. "Nothing held
         up" is genuinely news and has nowhere else to be said; "2 waiting" has. -->
    {#if needsYou === 0}
      <button class="hero-gate" onclick={() => onTab?.("operations")}>
        <span class="g-label">{t("stat.waiting")}</span>
        <span class="g-num">{needsYou}</span>
        <span class="g-hint">{t("stat.waitingClear")}</span>
      </button>
    {/if}
    <div class="pulse-row">
        <div class="stat">
          <div class="label">{t("stat.hour")}</div>
          <div class="value">{summary.tick}</div>
        </div>
        <div class="stat">
          <div class="label">{t("stat.actions")}</div>
          <div class="value">{summary.status.actions.toLocaleString(lang)}</div>
        </div>
        <div class="stat">
          <div class="label">{t("stat.tokens")}</div>
          <div class="value">
            {summary.status.tokens.toLocaleString(lang)}
            <span class="of">/ {summary.session_budget.toLocaleString(lang)}</span>
          </div>
        </div>
        <!-- `flow.throughput`, not `done_total`: that one lives in the `tasks` resource and reads
             `null` here. Measured against the live company before wiring it — the twelfth time in
             this restructuring that assuming a field would have shipped a blank number. -->
        <div class="stat">
          <div class="label">{t("flow.delivered")}</div>
          <div class="value">{summary.flow.throughput ?? 0}</div>
        </div>
      <div class="stat">
        <div class="label">{t("flow.wip")}</div>
        <div class="value">{summary.flow.wip ?? 0}</div>
      </div>
    </div>
    <div class="hero-state">
        {#if summary.running}
          <span class="badge ok">{t("badge.running")}</span>
          {#if summary.loop}<span class="badge">{t("badge.looping")}</span>{/if}
          {#if summary.stopping}<span class="badge warn">{t("badge.stopping")}</span>{/if}
        {/if}
      {#if summary.freezes > 0}
        <span class="badge warn">{t("badge.frozen")} · {summary.freezes}</span>
      {/if}
    </div>

    <!-- The run control, inside the band. Seeing what needs you and starting a day are the two things an
         operator does first, and they were a band and a card two rows apart — so the page opened with a
         number and made you scroll to act on it. -->
    <div class="hero-act">
{#if summary.running}
        <button disabled={busy === "run"} onclick={stopRun}>{t("run.stop")}</button>
      {:else}
        <!-- One column of three. See the note on `.run-choice`. -->
        <div class="run-choice">
          <button
            class="primary"
            disabled={busy === "run"}
            onclick={() => startRun(6, false)}
            title={t("run.tickTip")}
          >{t("run.h6")}</button>
          <button disabled={busy === "run"} onclick={() => startRun(24, false)}>{t("run.h24")}</button>
          <button disabled={busy === "run"} onclick={() => startRun(24, true)}>{t("run.loop")}</button>
        </div>
      {/if}
      {#if lastRun}
        <!-- An interrupted run says so in its own words, from the core. Nothing was resumed, and
             reporting it as finished would claim ticks that never happened. -->
        <p class="note">
          {#if lastRun.error}
            {lastRun.error}
          {:else}
            {t("progress.lastRun")}: {lastRun.ticks_run ?? 0} {t("progress.run")}
          {/if}
        </p>
      {/if}
      {#if jobs.length}
        <ul class="feed">
          {#each jobs.slice(0, 3) as job (job.id)}
            <li>
              <span class="badge {job.state === 'done' || job.state === 'running' ? 'ok' : 'danger'}"
                >{job.state}</span>
              <span class="muted grow">{job.progress || job.kind}</span>
            </li>
          {/each}
        </ul>
      {/if}
    </div>
  </section>


  <!-- Varied cells rather than a stack of identical ones: the log is wide because it is read, the
       meters are narrow because they are glanced at. -->
  <!-- The composition, top to bottom, and the reason each page now looks unlike the next: **what needs
       you and what you do about it**, then **what happened**, then **what it cost and what it produced**.
       It was six equal cells in a bento; a bento is a shape, not an order. -->
  <div class="grid cols">
    <!-- The reading column: what the agents did, then what they produced. **One grid child**, because in
         a two-column grid three children means the third wraps to a second row — which is how this page
         grew a 700x800 hole where its own rail should have been. -->
    <div class="stack">
    <!-- What the agents actually did. -->
    <section class="card">
      <div class="card-head">
        <div>
          <h2>{t("activity.title")}</h2>
          <p class="desc">{t("activity.desc")}</p>
        </div>
        {#if actions.length}
          <button class="link" onclick={() => onTab?.("operations")}>{t("activity.openLog")}</button>
        {/if}
      </div>
      {#if actions.length === 0}
        <Empty text={t("activity.empty")} />
      {:else}
        <ul class="feed">
          {#each actions.slice(0, 7) as action, i (action.ts + ":" + i)}
            <li>
              <span class="badge {action.ok ? 'ok' : 'danger'}"
                >{t(action.ok ? "badge.ok" : "badge.fail")}</span>
              <strong>{action.tool}</strong>
              <span class="who muted grow"><AgentIcon id={action.agent} />{action.agent}</span>
              <!-- Which provider answered, and whether the chain fell back. Schema 18 exists because
                   this was produced and thrown away: an operator read "Nothing usable drafted" as a
                   broken site generator while two providers were answering 429, after 365 026
                   tokens. -->
              {#if action.source}<span class="muted small mono">{action.source}</span>{/if}
              {#if action.fell_back}<span class="badge warn">{t("tier.chain")}</span>{/if}
            </li>
          {/each}
        </ul>
      {/if}
    </section>


    <!-- …and what it produced. The preview closes the reading column rather than trailing the page, so
         the two columns are comparable in height and the composition has a bottom instead of a hole. -->
    <section class="card">
      <div class="card-head">
        <div>
          <h2>{t("site.title")}</h2>
          <p class="desc">{t("site.desc")}</p>
        </div>
        {#if site}
          <div class="actions">
            <!-- Regenerate is the safe, expected action and takes the accent. Publish is the one with a
                 real-world effect — it puts a site on the internet — so it takes the warm treatment this
                 console uses for exactly that, rather than being a quiet button beside a loud one. -->
            <button class="primary" disabled={busy === "site"} onclick={buildSite}>
              {t(site.built ? "site.regenerate" : "site.generate")}
            </button>
            {#if site.built}
              <button class="real" disabled={busy === "publish"} onclick={publish}>
                {busy === "publish" ? t("site.publishing") : t("site.publish")}
              </button>
            {/if}
          </div>
        {/if}
      </div>
      {#if site}
        {#if site.built}
          <!-- The preview, from `/site/<slug>/`. The frame is 16:9 and the document inside it is rendered
               at 400% and scaled to a quarter, so a whole page fits a card at a legible density — and
               `pointer-events: none` means a click lands on the card rather than inside somebody's site.
               Keyed on the mtime so regenerating actually repaints it instead of showing the old build. -->
          {#key site.mtime}
            <div class="site-matte">
            <div class="site-frame">
              <iframe src={`/site/${encodeURIComponent(company)}/`} title={t("site.title")} tabindex="-1"
              ></iframe>
            </div>
            </div>
          {/key}
          <p class="note">
            {new Date(site.mtime * 1000).toLocaleString(lang, {
              month: "short",
              day: "numeric",
              hour: "2-digit",
              minute: "2-digit",
            })}
            <!-- Which site this is. The console once previewed the generated path while the terminal
                 published the owned one, and both reported success — the second live divergence this
                 restructuring found. -->
            {#if site.owned}· {fill(t("site.pages"), { n: site.pages.length })}{/if}
          </p>
        {:else}
          <Empty text={t("site.none")} />
        {/if}
        {#if said}<p class="note">{said}</p>{/if}
      {/if}
    </section>

    </div>

    <!-- The rail: three small readings, each a fact about the day rather than a place to work. -->
    <div class="stack">
    <section class="card">
      <h2>{t("live.title")}</h2>
      <p class="desc">{t("live.desc")}</p>
      {#if golive}
        <div>
          <div class="kv">
            <span class="k">{t("live.payment")}</span>
            <span class="badge {golive.payment.wired ? 'ok' : 'warn'}"
              >{t(golive.payment.wired ? "live.paidOk" : "live.paidNo")}</span>
          </div>
          <div class="kv">
            <span class="k">{t("live.mail")}</span>
            <span class="badge {golive.mail.wired ? 'ok' : 'warn'}"
              >{t(golive.mail.wired ? "live.mailOk" : "live.mailNo")}</span>
          </div>
          <div class="kv">
            <span class="k">{t("live.hosting")}</span>
            <!-- Three states, not two: not hosted, a token set but nothing published yet, and live at
                 a URL. Collapsing the middle one would tell an operator who has done half the work
                 that they have done none of it. -->
            <span class="v">
              {#if golive.hosting.published_url}
                <a class="badge ok" href={golive.hosting.published_url} target="_blank" rel="noreferrer noopener">
                  {t("live.hostLive")}
                </a>
              {:else if golive.hosting.token_set}
                <span class="badge warn">{t("live.hostReady")}</span>
              {:else}
                <span class="badge">{t("live.hostNo")}</span>
              {/if}
            </span>
          </div>
        </div>
      {/if}
    </section>

    <section class="card">
      <h2>{t("pay.title")}</h2>
      <p class="desc">{t("pay.desc")}</p>
      {#if payments?.error}
        <p class="note">{t("pay.error")} {payments.error}</p>
      {:else if payments}
        <!-- `source` is "stripe", "mock" or "error" — never "live", which was my invention and would
             have labelled real charges as samples. Sample data reading as sales is the worst kind of
             wrong on the one card about money, so the mock says so and an error says which. -->
        {#if payments.source === "mock"}<p class="note">{t("pay.mock")}</p>{/if}
        {#if payments.source === "error"}<p class="note">{t("pay.error")} {payments.error}</p>{/if}
        <div class="stat">
          <div class="label">{t("pay.total")}</div>
          <div class="value">{(payments.total_paid ?? 0).toFixed(2)}</div>
        </div>
        {#if payments.payments.length === 0}
          <!-- The total above stays, at 0.00. A card whose whole content is a sentence, beside two cards
               full of readings, was the only one on the rail with nothing to read. -->
          <Empty text={t("pay.none")} />
        {:else}
          <ul class="feed">
            {#each payments.payments.slice(0, 4) as charge, i (charge.ts + ":" + i)}
              <li>
                <strong>{charge.amount.toFixed(2)} {charge.currency}</strong>
                <span class="muted grow">{charge.description}</span>
                {#if !charge.paid}<span class="badge danger">{t("badge.fail")}</span>{/if}
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
        <Empty text={t("spend.empty")} />
      {:else}
        <!-- Bars compare; with one series there is nothing to compare it to, and a single 100%-wide bar
             reads as a progress meter that is finished. Two or more and the bars come back. -->
        <div>
          {#each spend as row (row.agent)}
            {#if spend.length > 1}
              <div class="spend-row">
                <span class="who"><AgentIcon id={row.agent} />{row.agent}</span>
                <span class="bar"><i style="width: {Math.round(((row.t ?? 0) / busiest) * 100)}%"></i></span>
                <span class="n">{row.t.toLocaleString(lang)}</span>
              </div>
            {:else}
              <div class="kv">
                <span class="k who"><AgentIcon id={row.agent} />{row.agent}</span>
                <span class="v num">{row.t.toLocaleString(lang)}</span>
              </div>
            {/if}
          {/each}
        </div>
        <!-- The session budget, in the card about what is being spent. It was on the status band as one
             of six numbers; here it is the denominator the rows above are a share of, which is what
             makes a card with one agent in it worth reading. -->
        <div class="kv">
          <span class="k">{t("progress.tokens")}</span>
          <span class="v num">
            {summary.status.tokens.toLocaleString(lang)} / {summary.session_budget.toLocaleString(lang)}
          </span>
        </div>
        <span class="bar">
          <i style="width: {Math.min(100, Math.round((summary.status.tokens / Math.max(1, summary.session_budget)) * 100))}%"></i>
        </span>
        <!-- A total of 0.00 and "nobody reported a cost" are different facts, and `cost_reported` is
             what separates them. Telling an operator on a paid key that they spent nothing would be
             the worst kind of wrong: quietly plausible. -->
        {#if summary.cost_reported}
          <p class="note">{money.toFixed(4)}</p>
        {:else}
          <p class="note">{t("spend.noCost")}</p>
        {/if}
      {/if}
    </section>

    </div>
  </div>

{/if}

<style>
  /* Only what this page has. The card, the hero, the bento, the badges, the stats and the buttons all
     come from `console.css`: they are the console's language, not the Overview's. */
  /* Three across, in one row, inside a horizontal band. Written here rather than in `console.css`
     because a Svelte-scoped `.run-choice` outranks any global `.hero-act .run-choice` — the third time
     this specificity trap has cost me a fix in the wrong file.

     Side by side in a *card* they wrapped 2+1 in English and 1+2 in French; in the band there is room for
     all three on one line, and `flex` with no wrap keeps that true in both languages. */
  .run-choice { display: flex; gap: 7px; flex-wrap: nowrap; }
  .run-choice button { padding: 7px 11px; font-size: 12.5px; white-space: nowrap; }

  /* The glyph and the name read as one thing. */
  .who { display: inline-flex; align-items: center; gap: 6px; min-width: 0; }

  .hero-state {
    display: flex;
    gap: 8px;
    flex-wrap: wrap;
    justify-content: flex-end;
    min-height: 26px;
  }
  @media (max-width: 760px) {
    .hero-state { justify-content: flex-start; }
  }
</style>
