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
  import { untrack } from "svelte";
  import { get, post, Refused } from "./api.js";
  import Ticked from "./Ticked.svelte";
  import { fill, translator } from "./i18n.js";
  import Empty from "./Empty.svelte";
  import AgentIcon from "./AgentIcon.svelte";
  import Approval from "./Approval.svelte";

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
  // A card with nothing in it stops being a card. `hushed` was the second attempt — collapse it but
  // keep the border — and a blind review named the result exactly: five full-width bordered panels
  // holding one sentence each, consuming the top 400px, so the page's actual subject (the log)
  // started below the fold. The panels were the problem, not their height.
  //
  // So the empty ones become one line. `strip` is that line: label and a short value per quiet fact,
  // and the cards below render only when they have something to show. The mode and the ask-above
  // threshold are on it unconditionally, because "what the gate is set to" is the one fact an
  // operator wants without asking, and it is one clause long.
  let gateOn = $derived(Boolean(summary) && (summary.approvals.length || summary.inbox.length));
  let rulesOn = $derived(Boolean(summary) && (summary.rules ?? []).length > 0);
  let draftsOn = $derived((drafts?.drafts ?? []).length > 0);
  let memoryOn = $derived((memory?.memory ?? []).length > 0);

  // ── what the company has learned, organised ──────────────────────────────────
  //
  // Measured on the real company before designing this: **55 facts, 13 933 characters, 16 pinned,
  // written over 6.9 days** — about eight a day, mean fact 253 characters. Rendered as one flat list
  // that is a wall of paragraphs on day seven and an unreadable scroll by day thirty, and the store
  // caps unpinned rows at `CORP_MEMORY_MAX` (200) and drops the oldest past it, so it also starts
  // forgetting without saying so.
  //
  // Two axes were available without a schema change, and the useful one is `agent`. On the real
  // corpus: ceo 33, strategy 12, outreach 6, design 2, finance 2 — and those are genuinely different
  // kinds of fact (the CEO's conclusions, strategy's measurements, outreach's notes on named people).
  // Grouping is exact rather than a clustering heuristic, and every agent already has a glyph.
  //
  // Pinned facts come out as their own group and lead, because they are the operator's own selection
  // and the one group the cap will never touch.
  let memFilter = $state("");
  let memOpen = $state({});

  let memFacts = $derived.by(() => {
    const all = memory?.memory ?? [];
    const needle = memFilter.trim().toLowerCase();
    if (!needle) return all;
    return all.filter((f) =>
      `${f.fact ?? ""} ${f.why ?? ""} ${f.agent ?? ""}`.toLowerCase().includes(needle),
    );
  });

  let memGroups = $derived.by(() => {
    const pinned = memFacts.filter((f) => f.pinned);
    const byAgent = new Map();
    for (const fact of memFacts) {
      if (fact.pinned) continue;
      const who = fact.agent || "system";
      if (!byAgent.has(who)) byAgent.set(who, []);
      byAgent.get(who).push(fact);
    }
    // Biggest group first: on the real corpus the CEO writes 60% of them, and burying the largest
    // group under two of size 2 is the alphabetical ordering that makes a list feel arbitrary.
    const groups = [...byAgent.entries()]
      .sort((one, two) => two[1].length - one[1].length)
      .map(([who, facts]) => ({ key: who, agent: who, facts }));
    return pinned.length ? [{ key: "pinned", agent: "", facts: pinned }, ...groups] : groups;
  });

  // Open by default only while there is little to read, and always when a filter is narrowing it —
  // a search that makes you click five times to see its own results is not a search. The threshold is
  // the point where the flat list stopped being readable on the real data.
  const MEM_FLAT = 12;
  let memAutoOpen = $derived(memFacts.length <= MEM_FLAT || Boolean(memFilter.trim()));
  const memShown = (group) => memAutoOpen || memOpen[group.key] || group.key === "pinned";
  // `SHOWN` per group, not per card. The pinned group is open by default and had sixteen facts in it
  // on the real company — "always open" and "all of it" are different promises, and only the first one
  // is worth making.
  const memRows = (group) =>
    memOpen[`g:${group.key}`] ? group.facts : group.facts.slice(0, SHOWN);

  // Each quiet fact says something different. A review counted "nothing yet" three times in one row
  // and it was right — one value repeated is one value, and a strip of it reads as a placeholder
  // rather than as five readings. So the drafts entry carries its real number (`0 of 5` is a fact and
  // a cap the operator can hit), the board says `empty`, and the two that genuinely have no count say
  // `none`. Only "what the company learned" keeps `nothing yet`, where it is literally the state.
  let strip = $derived.by(() => {
    if (!summary) return [];
    const items = [];
    if (!gateOn) items.push([t("ops.waiting"), t("ops.stripNone")]);
    if (!rulesOn) items.push([t("ops.rules"), t("ops.stripNone")]);
    if (boardEmpty) items.push([t("ops.backlog"), t("col.empty")]);
    if (!draftsOn && drafts) {
      items.push([t("dft.title"), fill(t("dft.queued"), { n: drafts.queued, cap: drafts.cap })]);
    }
    if (!memoryOn) items.push([t("mem.title"), t("ops.stripNothing")]);
    return items;
  });

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

  // Company, and nothing else. `untrack` is load-bearing, and this is what it cost to find out:
  // `refresh` is called synchronously from here and reads `summary?.running` to decide whether to
  // ask for the log — so the effect tracked `summary`, which the same effect writes. Measured on the
  // built bundle: **105 requests in two seconds**, five resources at ten hertz, for as long as the
  // tab was open. And because every re-run tore the interval down and made a new one, the five-second
  // poll this docstring describes never fired once.
  //
  // The trap is that the read is not visible from here: it is a frame down a call this line makes,
  // and an effect's dependencies are whatever it reads before its first await. Nothing static can see
  // that, so what `tests/test_console_effects.py` pins is this `untrack` and the interval teardown —
  // narrow, and enough to stop the two lines whose removal brings the loop back.
  $effect(() => {
    // Named so the linter and the reader both see that changing company re-runs both.
    const slug = company;
    if (!slug) return;
    untrack(() => {
      refresh({ slow: true });
      refreshQuiet();
    });
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

  const decide = (id, decision, remember = "", note = "") => {
    // The key is chosen before `t` is called, not inside it. `tests/test_console_tokens.py` scans
    // every string literal in a `t(...)` and treats it as a key, which means a comparison operand
    // sitting in there reads as an invented key — the guard was right and this is clearer anyway.
    const yes = decision === "approved";
    const key = remember ? "toast.remembered" : yes ? "toast.approved" : "toast.rejected";
    // The note arrives from `Approval.svelte`, which owns the field. It used to live in a keyed map
    // here, which is what a parent does when the row is markup it wrote; now the row is a component
    // and the text belongs to it.
    return act(id, "/api/v1/approvals", { id, decision, remember, note }, {
      toast: t(key),
    });
  };

  const revoke = (tool) =>
    act(`rule:${tool}`, "/api/v1/rules", { tool, company }, { toast: t("toast.revoked") });

  const remember = (id, action) =>
    act(`mem:${id}`, "/api/v1/memory", { id, action }, { toast: t("toast.memory"), quiet: true });

  const setDraft = (id, state) =>
    act(`dft:${id}`, "/api/v1/drafts", { id, state, company }, { quiet: true });

  // Per-task edits in flight, and which board column is expanded. Plain objects rather than one
  // `$state` per row: the rows come and go with every poll and a keyed map survives that.
  //
  // `notes` used to be here too, one entry per pending approval. It moved into `Approval.svelte` with
  // the row itself — a parent holding the text of a field it no longer renders is state looking for a
  // component to belong to.
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
  <!-- 0. Everything that is quiet, on one line. See `strip` above for why this is not five cards. -->
  <p class="strip">
    <span class="strip-item">
      <span class="strip-key">{t("ops.mode")}</span>
      <span class="strip-val">{summary.permission_mode}</span>
    </span>
    <span class="strip-item">
      <span class="strip-key">{t("ops.askAbove")}</span>
      <span class="strip-val">{t("risk." + summary.ask_above)}</span>
    </span>
    {#each strip as [key, value] (key)}
      <span class="strip-item">
        <span class="strip-key">{key}</span>
        <span class="strip-val muted">{value}</span>
      </span>
    {/each}
  </p>

  <!-- 1. The gate, full width and first.
       It shared a `.grid half` with the standing rules, so the one action this product exists for was
       the narrowest element on the page — its title wrapped, its buttons stacked — while the board of
       work a human never has to touch spanned the full 1440. A review called that out as the single
       biggest thing holding the page back and it was right: width is hierarchy, and the gate had none.
       `subject` is the treatment that says which card a page is for. -->
  {#if gateOn}
  <section class="card prose subject" class:attention={summary.approvals.length > 0}>
    <h2>{t("ops.waiting")}</h2>
    <p class="desc">{t("ops.waitingDesc")}</p>
    <!-- The mode and the threshold used to be repeated here. They are on the strip above now, where
         they are read whether or not anything is held — which is when an operator wants them. -->

    <!-- The full instance of the same component Overview renders compact. -->
    {#each summary.approvals as approval (approval.id)}
      <Approval {approval} {lang} {busy} onDecide={decide} />
    {/each}

  </section>
  {/if}

  <!-- 2. What the operator told the gate to stop asking about. Same rule: a card here means there is
       at least one rule to revoke. "No standing rule" is a clause, not a panel. -->
  {#if rulesOn}
  <section class="card">
    <h2>{t("ops.rules")}</h2>
    <p class="desc">{t("ops.rulesDesc")}</p>
    <div class="rows">
    {#each summary.rules as rule (rule.tool)}
      <div class="row">
        <div><strong>{rule.tool}</strong> <span class="muted">· {rule.scope}</span></div>
        <button class="danger-quiet" disabled={busy === `rule:${rule.tool}`} onclick={() => revoke(rule.tool)}>
          {t("ops.revoke")}
        </button>
      </div>
    {/each}
    </div>
  </section>
  {/if}

  <!-- 3. The board. -->
  <!-- One card: the heading and the five columns it names. It was a card containing a title and a
       sentence, with the columns as siblings *below* it — so the heading looked like a stray paragraph
       and the board looked like five unlabelled slabs. -->
  {#if !boardEmpty}
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
            <article class="kcard">
              <p class="title">{task.title}</p>
              <p class="meta">
                {task.target}
                · {#if task.tool}{task.tool}{:else}<span class="chip warn">{t("task.noTool")}</span>{/if}
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
                    <!-- Outline, not filled. A review counted the cost: with a filled primary on
                         every proposed card, one screen showed **five** of them, which destroys the
                         hierarchy the approvals card above establishes so carefully. The board is a
                         queue view — the decision surface is the gate, and the filled blue belongs
                         to it alone. Approving from here still works; it simply stops shouting. -->
                    <button disabled={busy === `task:${task.id}`} onclick={() => saveEdit(task, "approved")}>
                      {t("btn.approve")}
                    </button>
                    <button class="danger-quiet" disabled={busy === `task:${task.id}`} onclick={() => saveEdit(task, "rejected")}>
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
  {/if}

  <!-- 4 and 5, side by side: each was a full-width card holding a paragraph half its own width, so the
       right half of both was empty. Both are absent when empty; the strip carries them. -->
  {#if draftsOn || memoryOn}
  <div class="grid half">
  {#if draftsOn}
  <section class="card prose">
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
          <p class="draft-body">{draft.body ?? ""}</p>
          <div class="actions">
            <button onclick={() => copy(draft.body ?? "", draft.id)}>
              {copied === draft.id ? t("dft.copied") : t("dft.copy")}
            </button>
            {#if draft.state !== "published"}
              <!-- Outline. Publishing a draft matters, and it is still not the gate: two filled buttons
                   here beside the gate's two made four blue buttons on one page, and only one card on
                   this page is the decision surface. -->
              <button disabled={busy === `dft:${draft.id}`} onclick={() => setDraft(draft.id, "published")}>
                {t("dft.published")}
              </button>
            {/if}
            {#if draft.state !== "discarded"}
              <button class="danger-quiet" disabled={busy === `dft:${draft.id}`} onclick={() => setDraft(draft.id, "discarded")}>
                {t("dft.discard")}
              </button>
            {/if}
          </div>
        </article>
      {/each}
    {/if}
  </section>
  {/if}

  <!-- What the company learned, and the operator's veto over it. -->
  {#if memoryOn || memory?.memory_enabled === false}
  <section class="card prose">
    <h2>{t("mem.title")}</h2>
    <p class="desc">{t("mem.desc")}</p>
    {#if memory && !memory.memory_enabled}
      <p class="muted">{t("mem.off")}</p>
    {:else if memory}
      <!-- The cost, and the ceiling. Both were invisible: these facts are pasted into prompts, so
           their length is what the operator pays, and the store drops the oldest unpinned row past
           the cap whether or not anybody was told. -->
      <p class="strip">
        <span class="strip-item">
          <span class="strip-val">{fill(t("mem.budget"), {
            n: memory.memory.length,
            chars: (memory.chars ?? 0).toLocaleString(),
          })}</span>
        </span>
      </p>
      {#if memory.cap && memory.unpinned >= memory.cap * 0.8}
        <p class="banner warn">{fill(t("mem.nearCap"), { n: memory.unpinned, cap: memory.cap })}</p>
      {/if}

      <!-- The filter appears only once browsing has stopped working. A search box over eight facts is
           furniture. -->
      {#if memory.memory.length > MEM_FLAT}
        <input type="text" bind:value={memFilter} placeholder={t("mem.filter")} />
      {/if}

      {#each memGroups as group (group.key)}
        <section class="mgroup">
          <!-- The pinned group has no toggle: it is the operator's own list and the one the cap will
               never touch, so it is always open.
               Two concrete elements rather than one `<svelte:element this={…}>`. The dynamic form
               reads better and cost more than it looked: it pulls in Svelte's namespace-resolution
               code, which carries the literal `http://www.w3.org/2000/svg`, and
               `tests/test_console_bundle.py` refuses an absolute URL nobody declared — the guarantee
               being that this bundle fetches nothing from outside itself. An `{#if}` is cheaper than
               either declaring an exception or weakening that test. -->
          {#if group.key === "pinned"}
            <div class="mgroup-head">
              <span class="mgroup-name">{t("mem.pinnedGroup")}</span>
              <span class="muted small">{fill(t("mem.groupCount"), { n: group.facts.length })}</span>
            </div>
          {:else}
            <button
              class="mgroup-head"
              aria-expanded={memShown(group)}
              onclick={() => (memOpen[group.key] = !memShown(group))}
            >
              <AgentIcon id={group.agent} />
              <span class="mgroup-name">{group.agent}</span>
              <span class="muted small">{fill(t("mem.groupCount"), { n: group.facts.length })}</span>
            </button>
          {/if}

          {#if memShown(group)}
            <div class="rows">
            <!-- One fact is one disclosure, and that is what got this card from 3 921px to something
                 readable. The first version showed, per fact, three clamped lines *plus* its `why`
                 *plus* a "more" link *plus* two buttons — about 240px each, so sixteen pinned facts
                 were 3 800px of column. Collapsed a fact is two lines and nothing else; the reason it
                 was kept and the two irreversible buttons appear when you open it, which is also when
                 an operator is actually deciding about it. -->
            {#each memRows(group) as fact (fact.id)}
              {@const shown = Boolean(memOpen[`f:${fact.id}`])}
              <div class="mrow" class:open={shown}>
                <button
                  class="mrow-head"
                  aria-expanded={shown}
                  onclick={() => (memOpen[`f:${fact.id}`] = !shown)}
                >
                  <!-- The agent, per fact, only where the group heading is not already saying it.
                       Ten of the sixteen pinned facts on the real company were written by outreach,
                       design and finance, and grouping by agent had hidden that inside "Kept by you". -->
                  {#if group.key === "pinned"}<AgentIcon id={fact.agent || "system"} />{/if}
                  <span class="mfact-wrap">
                    <span
                      class="mfact"
                      class:open={shown}
                      data-short={(fact.fact ?? "").length < 120 ? "" : undefined}
                    >{fact.fact}</span>
                  </span>
                </button>
                {#if shown}
                  {#if fact.why}<p class="muted small mwhy">{fact.why}</p>{/if}
                  <div class="actions">
                    <button disabled={busy === `mem:${fact.id}`} onclick={() => remember(fact.id, fact.pinned ? "unpin" : "pin")}>
                      {t(fact.pinned ? "mem.unpin" : "mem.pin")}
                    </button>
                    <button class="danger-quiet" disabled={busy === `mem:${fact.id}`} onclick={() => remember(fact.id, "forget")}>
                      {t("mem.forget")}
                    </button>
                  </div>
                {/if}
              </div>
            {/each}
            {#if group.facts.length > SHOWN}
              <button class="link" onclick={() => (memOpen[`g:${group.key}`] = !memOpen[`g:${group.key}`])}>
                {memOpen[`g:${group.key}`]
                  ? t("col.less")
                  : fill(t("col.more"), { n: group.facts.length - SHOWN })}
              </button>
            {/if}
            </div>
          {/if}
        </section>
      {/each}
      {#if memFilter.trim() && !memFacts.length}<Empty text={t("mem.noMatch")} />{/if}
    {/if}
  </section>
  {/if}
  </div>
  {/if}

  <!-- 6. The audit trail, and the column that cost 365 026 tokens to be missing.
       This is the page. It was fifth of six equal panels and started below the fold at y≈520; now
       everything above it is either a one-line strip or a card that has something in it, so the log
       is what a reader lands on. `subject` is the treatment that says so. -->
  <section class="card subject">
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
  /* Lanes, and cards in them — which is the opposite of what this said before.
     The old rule stripped the columns of any surface, reasoning that a box inside a box is the drift
     that made every tab look like the same rectangle. The reasoning was right and the conclusion was
     wrong: with no lane and no card, five columns of work became, in a review's words, "a table
     pretending to be a board — the one screen that reads as raw data rendered by a developer".
     A box inside a box is only drift when both boxes are the *same* box. `--sunken` is a step below
     the card and the items are a step above the lane, so the nesting reads as depth rather than as
     repetition — and it is the second surface tier the whole console was missing. */
  .board :global(.kcol) {
    background: var(--sunken);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 10px 8px 4px;
  }
  .board :global(.kcol h3) { padding: 0 4px 9px; }
  /* Each item is an object you can count and act on, not a line in a list. */
  .board :global(.kcard) {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 9px 10px;
    margin-bottom: 6px;
  }
  .board :global(.kcard:hover) { border-color: var(--border-ui); background: var(--surface); }
  /* A lane is about 200px, and Edit + Approve + Reject at full size is 230 — so `Reject` wrapped
     onto a line of its own and the three actions read as two groups. Compacted, they hold one
     row. The tiers are unchanged: primary, text, destructive text. */
  .board :global(.kcard .actions) { gap: 6px; margin-top: 8px; }
  .board :global(.kcard .actions button) { padding: 4px 9px; font-size: 12px; }
  .board :global(.kcard .actions button.link) { padding: 4px 4px; }
  .posture { font-size: 13.5px; margin: 0; color: var(--muted); }
  .row.block { display: block; }
  .row.block header { display: flex; gap: 7px; align-items: center; flex-wrap: wrap; }
  .actions { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; margin-top: 10px; }


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
