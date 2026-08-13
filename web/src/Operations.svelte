<script>
  /**
   * The second tab: the board, the standing rules, what the company learned, and the audit trail.
   *
   * Where Overview gives an approval two buttons, this gives it the panel — what the tool does, why
   * this one stopped here, what the agent actually wrote, what yes and no each mean. Both are worth
   * having: an operator clearing a queue wants the buttons, and an operator meeting an unfamiliar
   * tool wants the paragraph. `summary` already resolves all of it (`app_overview.summary` builds
   * `detail` server-side, precisely so two clients cannot render two different explanations).
   *
   * ## What polls, and what does not
   *
   * Five resources, and polling all five every five seconds would undo the point of splitting them.
   * So the cadence follows what actually changes on a tick:
   *
   *   * `summary` and `tasks` — every tick, so every poll;
   *   * `activity` — only while a run is going. A log nobody is writing to is a request for 304s;
   *   * `memory` and `drafts` — on mount, and after a write that touches them. 17.7 KB that changes
   *     almost never is the resource an ETag saves most, and not asking at all saves the round trip
   *     as well.
   *
   * ## Two things the shipped page put here and this does not
   *
   * **Backup** moves to Settings. It is a maintenance action that happens to have been rendered next
   * to the audit log, and "by layer, not by page" is the rule that kept `handlers.py` readable —
   * a tab is not a reason for two unrelated things to live together.
   *
   * **The inbox and the approval queue** lead Overview instead, because the human gate is the
   * subject of this product and should not have to be looked for. The full detail is here.
   */
  import { get, post, Refused } from "./api.js";
  import Ticked from "./Ticked.svelte";
  import { fill, translator } from "./i18n.js";
  import Empty from "./Empty.svelte";
  import AgentIcon from "./AgentIcon.svelte";

  let { lang, company, token = "" } = $props();
  let t = $derived(translator(lang));

  let summary = $state(null);
  let board = $state(null);
  let actions = $state([]);
  let memory = $state(null);
  let drafts = $state(null);
  let failure = $state(null);
  let busy = $state("");
  let said = $state("");

  // The interval the old page used for a 48 530-byte payload. Unchanged, over resources that are
  // 2 859 and 21 KB, with the 17.7 KB one not in the loop at all.
  const POLL_MS = 5000;

  // The board's order, and it is the order work moves in. `done` last and bounded: the store keeps
  // all of it and `done_total` is the true count, which is why the header reads that and not the
  // row count — a column showing 60 for a company that finished three hundred is the failure that
  // number exists to prevent.
  const COLUMNS = ["proposed", "approved", "in_progress", "waiting", "done"];

  // Whether the board has anything at all. Said once, under the five columns, rather than five times
  // inside them: "Empty" under a 0 in each of five lanes is five placeholders for one fact.
  let boardEmpty = $derived(
    Boolean(board) && COLUMNS.every((column) => (board.tasks[column] ?? []).length === 0),
  );
  const SHOWN = 6;

  const q = () => `company=${encodeURIComponent(company)}`;

  async function refresh({ slow = false } = {}) {
    try {
      const wanted = [get(`/api/v1/summary?${q()}`, { token }), get(`/api/v1/tasks?${q()}`, { token })];
      // Only while something is writing to it. Asking a still log for changes is a request whose
      // best case is a 304, and its best case is still a round trip.
      const live = summary?.running || slow;
      if (live) wanted.push(get(`/api/v1/activity?${q()}`, { token }));
      const [s, b, a] = await Promise.all(wanted);
      summary = s;
      board = b;
      if (a) actions = a.recent_actions ?? [];
      failure = null;
    } catch (e) {
      failure = e instanceof Refused ? e : new Refused(0, { error: { message: String(e) } });
    }
  }

  /** The two that change on a write rather than on a tick. Fetched, not polled. */
  async function refreshQuiet() {
    try {
      const [m, d] = await Promise.all([
        get(`/api/v1/memory?${q()}`, { token }),
        get(`/api/v1/drafts?${q()}`, { token }),
      ]);
      memory = m;
      drafts = d;
    } catch (e) {
      failure = e instanceof Refused ? e : new Refused(0, { error: { message: String(e) } });
    }
  }

  $effect(() => {
    // Named so the linter and the reader both see that changing company re-runs both.
    const slug = company;
    if (!slug) return;
    refresh({ slow: true });
    refreshQuiet();
    const timer = setInterval(() => refresh(), POLL_MS);
    return () => clearInterval(timer);
  });

  /** One place that runs a write, reports it, and refreshes. Every button below goes through it. */
  async function act(key, path, payload, { toast = "", quiet = false } = {}) {
    busy = key;
    said = "";
    try {
      const done = await post(path, payload, { token });
      // `gated` is the by-name refusal and it has to be said out loud: the operator asked for a
      // standing rule and the answer to that half was no, because their own company file names the
      // tool in `hitl_tools`. A button that silently does two thirds of what it says is worse than
      // one that does nothing.
      said = done.gated ? `${t("ops.whyGated")} ${done.gated}` : toast;
      await refresh();
      if (quiet) await refreshQuiet();
      return done;
    } catch (e) {
      failure = e;
      return null;
    } finally {
      busy = "";
    }
  }

  const decide = (id, decision, remember = "") => {
    // The key is chosen before `t` is called, not inside it. `tests/test_console_tokens.py` scans
    // every string literal in a `t(...)` and treats it as a key, which means a comparison operand
    // sitting in there reads as an invented key — the guard was right and this is clearer anyway.
    const yes = decision === "approved";
    const key = remember ? "toast.remembered" : yes ? "toast.approved" : "toast.rejected";
    return act(id, "/api/v1/approvals", { id, decision, remember, note: notes[id] ?? "" }, {
      toast: t(key),
    });
  };

  const revoke = (tool) =>
    act(`rule:${tool}`, "/api/v1/rules", { tool, company }, { toast: t("toast.revoked") });

  const remember = (id, action) =>
    act(`mem:${id}`, "/api/v1/memory", { id, action }, { toast: t("toast.memory"), quiet: true });

  const setDraft = (id, state) =>
    act(`dft:${id}`, "/api/v1/drafts", { id, state, company }, { quiet: true });

  // Per-approval note text, and per-task edits in flight. Plain objects rather than one `$state`
  // per row: the rows come and go with every poll and a keyed map survives that.
  let notes = $state({});
  let opened = $state({});
  let editing = $state(null);
  let draftEdit = $state({});
  let copied = $state("");

  function startEdit(task) {
    editing = task.id;
    draftEdit = { target: task.target ?? "", tool: task.tool ?? "", priority: task.priority ?? 0 };
  }

  async function saveEdit(task, decision = null) {
    const payload = { id: task.id, ...draftEdit };
    if (decision) payload.decision = decision;
    const done = await act(`task:${task.id}`, "/api/v1/tasks", payload, {
      toast: t(decision ? "toast.taskAssigned" : "task.saved"),
    });
    if (done) editing = null;
  }

  async function copy(text, id) {
    try {
      await navigator.clipboard.writeText(text);
      copied = id;
    } catch {
      // No clipboard permission is not a failure worth a banner: the text is on screen and can be
      // selected. Saying nothing is the honest answer to "the browser said no".
      copied = "";
    }
  }

  // Which tools each enabled role could actually carry, resolved by the core from the roster's
  // playbooks — so an operator assigning a task picks from real choices instead of finding out what
  // tool names exist. Suggested, not decided: `role_tool` is what the roster would use.
  let roles = $derived(Object.keys(summary?.agent_tools ?? {}).sort());
  let toolsFor = $derived((role) => summary?.agent_tools?.[role] ?? []);
  let proposalsMine = $derived(Boolean(summary?.proposals_need_you));
</script>

{#if failure}
  <p class="banner danger">
    {failure.message}
    {#if failure.code}<code>{failure.code}</code>{/if}
  </p>
{/if}
{#if said}<p class="banner ok">{said}</p>{/if}

{#if !summary || !board}
  <p class="muted">{t("docs.reading")}</p>
{:else}
  <!-- 1. The gate, with the whole explanation rather than two buttons. It is warm-tinted only when
       something is actually held, so "nothing waits" and "three things wait" are different at a
       glance rather than the same card with different text in it. -->
  <div class="grid cols">
  <section class="card" class:attention={summary.approvals.length > 0}>
    <h2>{t("ops.waiting")}</h2>
    <p class="desc">{t("ops.waitingDesc")}</p>
    <p class="posture muted">
      <!-- The mode name verbatim: `discuss`, `interactive`, `auto`, `custom` are a closed vocabulary
           with no keys in the table, and inventing `tier.interactive` would have printed the key. -->
      {t("ops.mode")}: <strong>{summary.permission_mode}</strong>
      · {t("ops.askAbove")} <strong>{t("risk." + summary.ask_above)}</strong>
    </p>

    {#each summary.approvals as approval (approval.id)}
      <article class="row block">
        <header>
          <strong>{approval.tool}</strong>
          <span class="badge risk {approval.risk}">{t("risk." + approval.risk)}</span>
          <span class="muted">· {t("ops.requestedBy")} {approval.agent}</span>
        </header>

        <button class="link" onclick={() => (opened[approval.id] = !opened[approval.id])}>
          {t("ops.more")}
        </button>

        {#if opened[approval.id]}
          <dl class="detail">
            <dt>{t("ops.whatItDoes")}</dt><dd>{approval.detail.does}</dd>
            {#if approval.detail.why}
              <dt>{t("ops.whyStopped")}</dt><dd>{approval.detail.why}</dd>
            {/if}
            <dt>{t("ops.riskMeans")}</dt><dd>{approval.detail.risk_means}</dd>
            <dt>{t("ops.ifYes")}</dt><dd>{approval.detail.on_approve}</dd>
            <dt>{t("ops.ifNo")}</dt><dd>{approval.detail.on_reject}</dd>
          </dl>
          {#if approval.detail.draft}
            <details>
              <summary>{t("ops.fullDraft")}</summary>
              <pre>{approval.detail.draft}</pre>
            </details>
          {/if}
        {/if}

        <label class="note">
          <span class="muted">{t("ops.note")}</span>
          <input value={notes[approval.id] ?? ""} oninput={(e) => (notes[approval.id] = e.currentTarget.value)} />
        </label>

        <div class="actions">
          <button class="primary" disabled={busy === approval.id} onclick={() => decide(approval.id, "approved")}>
            {t("btn.approve")}
          </button>
          {#if approval.can_remember}
            <button disabled={busy === approval.id} onclick={() => decide(approval.id, "approved", "always")}>
              {t("ops.always")}
            </button>
          {/if}
          <button disabled={busy === approval.id} onclick={() => decide(approval.id, "rejected")}>
            {t("btn.reject")}
          </button>
        </div>
      </article>
    {/each}

    {#if summary.approvals.length === 0 && summary.inbox.length === 0}
      <Empty text={t("ops.calm")} />
    {/if}
  </section>

  <!-- 2. What the operator told the gate to stop asking about. -->
  <section class="card">
    <h2>{t("ops.rules")}</h2>
    <p class="desc">{t("ops.rulesDesc")}</p>
    <div class="rows">
    {#each summary.rules as rule (rule.tool)}
      <div class="row">
        <div><strong>{rule.tool}</strong> <span class="muted">· {rule.scope}</span></div>
        <button disabled={busy === `rule:${rule.tool}`} onclick={() => revoke(rule.tool)}>
          {t("ops.revoke")}
        </button>
      </div>
    {/each}
    </div>
    {#if summary.rules.length === 0}<Empty text={t("ops.rulesEmpty")} />{/if}
  </section>
  </div>

  <!-- 3. The board. -->
  <!-- One card: the heading and the five columns it names. It was a card containing a title and a
       sentence, with the columns as siblings *below* it — so the heading looked like a stray paragraph
       and the board looked like five unlabelled slabs. -->
  <section class="card board">
    <div>
      <h2>{t("ops.backlog")}</h2>
      <p class="desc">{t("ops.backlogDesc")}</p>
    </div>
    {#if boardEmpty}
      <!-- No columns at all when there is nothing in any of them. Five headers over five hairlines with
           a single orphaned "Empty" beneath reads as a board that failed to render rather than as an
           empty one — and the counts are all zero, so the columns are carrying no information either. -->
      <Empty text={t("col.empty")} />
    {:else}
    <div class="kanban">
      {#each COLUMNS as column (column)}
        {@const rows = board.tasks[column] ?? []}
        <div class="kcol">
          <h3>
            <!-- "Proposed, your call" only when nobody else will look. The CEO reviews proposals on
                 its own cadence and that is the point of having one; the old page counted every
                 proposal as the operator's and made a company noticing something small read as it
                 stopping to ask permission for trivia. The core decides this, not the page. -->
            {#if column === "proposed"}
              {t(proposalsMine ? "col.proposed" : "col.proposedCeo")}
            {:else}
              {t("col." + column)}
            {/if}
            <span class="count">{column === "done" ? board.done_total : rows.length}</span>
          </h3>

          {#each rows.slice(0, opened[`col:${column}`] ? rows.length : SHOWN) as task (task.id)}
            <article class="kcard" class:untooled={!task.tool}>
              <p class="title">{task.title}</p>
              <p class="meta">
                {task.target}
                · {task.tool || t("task.noTool")}
                {#if task.priority}· p{task.priority}{/if}
              </p>

              {#if editing === task.id}
                <div class="edit">
                  <select value={draftEdit.target} onchange={(e) => (draftEdit.target = e.currentTarget.value)}>
                    {#each roles as role}<option value={role}>{role}</option>{/each}
                  </select>
                  <select value={draftEdit.tool} onchange={(e) => (draftEdit.tool = e.currentTarget.value)}>
                    <option value="">{t("task.noTool")}</option>
                    {#each toolsFor(draftEdit.target) as tool}<option value={tool}>{tool}</option>{/each}
                  </select>
                  <div class="actions">
                    <button disabled={busy === `task:${task.id}`} onclick={() => saveEdit(task)}>{t("task.save")}</button>
                    {#if task.status === "proposed"}
                      <button disabled={busy === `task:${task.id}`} onclick={() => saveEdit(task, "approved")}>
                        {t("ib.assign")}
                      </button>
                    {/if}
                    <button class="link" onclick={() => (editing = null)}>{t("task.cancel")}</button>
                  </div>
                </div>
              {:else}
                <div class="actions">
                  <button class="link" onclick={() => startEdit(task)}>{t("task.edit")}</button>
                  {#if task.status === "proposed"}
                    <button class="primary" disabled={busy === `task:${task.id}`} onclick={() => saveEdit(task, "approved")}>
                      {t("btn.approve")}
                    </button>
                    <button disabled={busy === `task:${task.id}`} onclick={() => saveEdit(task, "rejected")}>
                      {t("btn.reject")}
                    </button>
                  {/if}
                </div>
              {/if}
            </article>
          {/each}

          {#if rows.length > SHOWN}
            <button class="link" onclick={() => (opened[`col:${column}`] = !opened[`col:${column}`])}>
              {opened[`col:${column}`] ? t("col.less") : fill(t("col.more"), { n: rows.length - SHOWN })}
            </button>
          {/if}
          {#if column === "done" && board.done_total > rows.length}
            <p class="muted small">{fill(t("col.rest"), { n: board.done_total - rows.length })}</p>
          {/if}
          <!-- Nothing per column. Five columns each printing "Empty" under a 0 is five placeholders
               where the board itself can say it once, below. -->
        </div>
      {/each}
    </div>
    {/if}
  </section>

  <!-- 4 and 5, side by side: each was a full-width card holding a paragraph half its own width, so the
       right half of both was empty. -->
  <div class="grid half">
  <section class="card">
    <h2>{t("dft.title")}</h2>
    <p class="desc">{t("dft.desc")}</p>
    {#if drafts}
      <p class="muted small">{fill(t("dft.queued"), { n: drafts.queued, cap: drafts.cap })}</p>
      {#if drafts.queued >= drafts.cap}<p class="banner warn">{t("dft.full")}</p>{/if}
      {#each drafts.drafts as draft (draft.id)}
        <article class="row block">
          <header>
            <span class="badge">{t("dft.state." + draft.state)}</span>
            <span class="muted">· {draft.kind ?? ""} {draft.channel ?? ""}</span>
          </header>
          <pre>{draft.body ?? ""}</pre>
          <div class="actions">
            <button onclick={() => copy(draft.body ?? "", draft.id)}>
              {copied === draft.id ? t("dft.copied") : t("dft.copy")}
            </button>
            {#if draft.state !== "published"}
              <button disabled={busy === `dft:${draft.id}`} onclick={() => setDraft(draft.id, "published")}>
                {t("dft.published")}
              </button>
            {/if}
            {#if draft.state !== "discarded"}
              <button disabled={busy === `dft:${draft.id}`} onclick={() => setDraft(draft.id, "discarded")}>
                {t("dft.discard")}
              </button>
            {/if}
          </div>
        </article>
      {/each}
      {#if drafts.drafts.length === 0}<p class="muted">{t("dft.none")}</p>{/if}
    {/if}
  </section>

  <!-- What the company learned, and the operator's veto over it. -->
  <section class="card">
    <h2>{t("mem.title")}</h2>
    <p class="desc">{t("mem.desc")}</p>
    {#if memory && !memory.memory_enabled}
      <p class="muted">{t("mem.off")}</p>
    {:else if memory}
      {#each memory.memory as fact (fact.id)}
        <div class="row">
          <div>
            {fact.fact}
            {#if fact.pinned}<span class="badge">{t("mem.pinned")}</span>{/if}
            {#if fact.why}<p class="muted small">{fact.why}</p>{/if}
          </div>
          <div class="actions">
            <button disabled={busy === `mem:${fact.id}`} onclick={() => remember(fact.id, fact.pinned ? "unpin" : "pin")}>
              {t(fact.pinned ? "mem.unpin" : "mem.pin")}
            </button>
            <button disabled={busy === `mem:${fact.id}`} onclick={() => remember(fact.id, "forget")}>
              {t("mem.forget")}
            </button>
          </div>
        </div>
      {/each}
      {#if memory.memory.length === 0}<p class="muted">{t("mem.none")}</p>{/if}
    {/if}
  </section>
  </div>

  <!-- 6. The audit trail, and the column that cost 365 026 tokens to be missing. -->
  <section class="card">
    <h2>{t("ops.log")}</h2>
    <p class="desc">{t("ops.logDesc")}</p>
    <div class="scroll">
      <table>
        <thead>
          <tr>
            <th>{t("th.time")}</th><th>{t("th.agent")}</th><th>{t("th.tool")}</th>
            <th>{t("th.state")}</th><th>{t("th.output")}</th>
          </tr>
        </thead>
        <tbody>
          {#each actions as action, i (action.ts + ":" + i)}
            <tr>
              <td class="num">
                {new Date(action.ts * 1000).toLocaleString(lang, {
                  month: "short",
                  day: "numeric",
                  hour: "2-digit",
                  minute: "2-digit",
                })}
              </td>
              <td class="who"><AgentIcon id={action.agent} />{action.agent}</td>
              <td>{action.tool}</td>
              <td>
                <span class="badge {action.ok ? 'ok' : 'danger'}">{t(action.ok ? "badge.ok" : "badge.fail")}</span>
                <!-- Which provider answered, and whether the chain fell back. Schema 18 exists
                     because this was produced and thrown away: an operator read "Nothing usable
                     drafted" as a broken site generator while groq and cerebras both answered 429,
                     and by then it had cost 365 026 tokens. -->
                {#if action.source}<span class="muted small">{action.source}</span>{/if}
                {#if action.fell_back}<span class="badge warn">{t("tier.chain")}</span>{/if}
              </td>
              <td class="out"><Ticked text={action.output} /></td>
            </tr>
          {/each}
          {#if actions.length === 0}
            <tr><td colspan="5" class="muted">{t("ops.logEmpty")}</td></tr>
          {/if}
        </tbody>
      </table>
    </div>
  </section>
{/if}

<style>
  /* Only what Operations has. The card, the rows, the badges, the buttons, the board columns and the
     tables are the console's language and live in `console.css` — including the kanban, which the
     Overview does not use but which belongs to the language rather than to this file. */
  .board { gap: 16px; }
  /* Inside a card, a column needs no surface of its own: the card is the surface. A border and a
     header rule are enough to say "column", and boxing each one again inside a box is the drift that
     made every tab look like a stack of the same rectangle. */
  .board :global(.kcol) { background: none; border: 0; border-radius: 0; padding: 0; }
  .board :global(.kcol h3) { padding: 2px 0 10px; }
  .board :global(.kcard) { padding: 11px 0; }
  .posture { font-size: 13.5px; margin: 0; color: var(--muted); }
  .row.block { display: block; }
  .row.block header { display: flex; gap: 7px; align-items: center; flex-wrap: wrap; }
  .actions { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; margin-top: 10px; }

  /* The five risk tiers, and the ramp is the point: read is furniture, money is the one an operator
     must never approve by reflex. */
  .badge.risk.read, .badge.risk.write_local { color: var(--muted); }
  .badge.risk.external { color: var(--warn); background: var(--warn-soft); }
  .badge.risk.code, .badge.risk.money { color: var(--danger); background: var(--danger-soft); }

  .count { color: var(--muted); font-variant-numeric: tabular-nums; font-weight: 400; }
  .detail { display: grid; grid-template-columns: auto minmax(0, 1fr); gap: 4px 16px; margin: 10px 0; font-size: 13.5px; }
  .detail dt { color: var(--muted); }
  .detail dd { margin: 0; }
  .note { display: flex; gap: 8px; align-items: center; margin-top: 10px; font-size: 13.5px; }
  .note input { flex: 1; }
  pre {
    margin: 8px 0 0;
    white-space: pre-wrap;
    max-height: 14rem;
    overflow: auto;
    background: var(--raised);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 10px 12px;
    font-size: 13px;
  }
  /* A task with no tool completes having done nothing — 22 of 24 on one company — so it is marked
     rather than left looking like the others. */
  .kcard.untooled { border-left: 2px solid var(--warn); padding-left: 10px; }
  .kcard .title { margin: 0; font-size: 13.5px; }
  .kcard .meta { margin: 3px 0 0; }
  .edit { display: grid; gap: 6px; margin-top: 8px; }
  .scroll { overflow-x: auto; }
  .num { font-variant-numeric: tabular-nums; white-space: nowrap; }
  .who { white-space: nowrap; }
  .who :global(svg) { margin-right: 6px; }
  .out { color: var(--muted); }
  .state.ok { color: var(--ok); }
  .state.bad { color: var(--danger); }
</style>
