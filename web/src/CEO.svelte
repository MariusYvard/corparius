<script>
  /**
   * The sixth tab: talking to the CEO, and the buttons that make its answers true.
   *
   * ## The conversation is a table now
   *
   * This tab could not have been built honestly before schema 21. The history lived in
   * `UiState.chats`, a deque in the console's process, so closing the console lost every exchange —
   * including the ones where the CEO paused a role or set a focus, which are exactly the turns an
   * operator wants to look back at. A phone could not read any of it, and `corparius ceo` was a
   * stranger to the whole thread.
   *
   * `chat_turns` fixes all three: one conversation per company, whoever is typing. Ask in a terminal,
   * read the answer here.
   *
   * ## The reply and the action are two halves of one answer
   *
   * `directives.apply` runs inside the service, so a CEO that says "I will pause the campaigns" has
   * paused them — or the sentence is corrected before it reaches this screen. That shape exists
   * because the empty promise was the failure it was written to end: asked to put design on
   * `claudecode:opus`, the CEO once answered *"J'approuve l'utilisation de Claudecode Opus pour le
   * design"* and wrote nothing.
   *
   * `proposal` is the half the CEO will **not** do itself. It names an endpoint and a body, the
   * operator presses the button, and the client posts it. Rendering the reply and dropping the
   * proposal would hide a decision the CEO is waiting on — which is why a terminal prints it too.
   *
   * ## Not polled
   *
   * A conversation changes when somebody says something. The one exception is worth having and is not
   * here yet: a run in another window can add turns, and this will not see them until the operator
   * sends or reloads. Stated rather than papered over with an interval that costs a request every five
   * seconds to catch something that happens twice a day.
   */
  import { get, post, Refused } from "./api.js";
  import { translator } from "./i18n.js";
  import AgentIcon from "./AgentIcon.svelte";

  // `onTab` is what makes a next step a redirect rather than an instruction. Optional, like
  // Overview's: a caller that does not pass it gets steps that read as advice instead of crashing.
  let { lang, company, token = "", active = true, onTab = undefined } = $props();

  // A step names either a tab or an action. The one action is `run`, and rather than start a run from
  // here this sends the operator to the tab that owns the control — one place starts a run, and a
  // second entry point would be the "two surfaces, one job" defect this codebase keeps finding. The
  // redirect is still the redirect: they land on the button with nothing left to look for.
  const goto = (step) => onTab?.(step.tab || "overview");
  let t = $derived(translator(lang));

  let history = $state([]);
  let summary = $state(null);
  let failure = $state(null);
  let sending = $state(false);
  let draft = $state("");
  let proposal = $state(null);
  let said = $state("");

  const q = () => `company=${encodeURIComponent(company)}`;

  async function load() {
    try {
      const [chat, s] = await Promise.all([
        get(`/api/v1/chat?${q()}`, { token }),
        get(`/api/v1/summary?${q()}`, { token }),
      ]);
      history = chat.history ?? [];
      summary = s;
      failure = null;
    } catch (e) {
      failure = e instanceof Refused ? e : new Refused(0, { error: { message: String(e) } });
    }
  }

  // Read, not required — see `Documents.svelte`. Coming back reloads the conversation; hovering the
  // tab loads it before the click.
  $effect(() => {
    active;
    if (company) load();
  });

  async function send(text) {
    const message = String(text ?? draft).trim();
    if (!message || sending) return;
    sending = true;
    said = "";
    proposal = null;
    // Shown immediately, so the operator sees their own question while the model is thinking. Replaced
    // by the server's history on the answer — this optimistic turn is a rendering convenience and
    // never the record.
    history = [...history, { role: "user", text: message }];
    draft = "";
    try {
      // `company` in the **body**, not the query. A POST reads the slug from what it was sent, and
      // this route declares `needs_slug`, so a body without it is a 404 before any handler runs:
      // every message to the CEO answered "not found" until this line did.
      const done = await post("/api/v1/chat", { company, message }, { token });
      history = done.history ?? history;
      proposal = done.proposal ?? null;
    } catch (e) {
      failure = e;
      // Take the optimistic turn back out: it was never sent, and leaving it would show a question in
      // the transcript that the CEO never received.
      history = history.slice(0, -1);
    } finally {
      sending = false;
    }
  }

  async function accept() {
    if (!proposal) return;
    sending = true;
    try {
      const body = proposal.needs_company ? { ...proposal.body, company } : { ...proposal.body };
      await post(proposal.endpoint, body, { token });
      said = t("ceo.launched");
      proposal = null;
      await load();
    } catch (e) {
      failure = e;
    } finally {
      sending = false;
    }
  }

  async function forget() {
    try {
      await post("/api/v1/chat/forget", { company }, { token });
      history = [];
      proposal = null;
    } catch (e) {
      failure = e;
    }
  }

  const SUGGESTIONS = ["ceo.s1", "ceo.s2", "ceo.s3", "ceo.s4"];
  let mockOn = $derived(Boolean(summary?.llm_mock));
</script>

{#if failure}
  <p class="banner danger">
    {failure.message}
    {#if failure.code}<code>{failure.code}</code>{/if}
  </p>
{/if}
{#if said}<p class="banner ok">{said}</p>{/if}

<section class="card chat" class:talking={history.length > 0}>
  <!-- An identity header, because this tab is a conversation with somebody. It carried the shipped
       page's pixel-art portrait and no longer does: three blind design reviews independently read the
       11-icon set as emoji placeholder art — "a red heart for the social agent" — at 36px and at 20px.
       The art is charming in a terminal and it does not survive being next to a monochrome line-icon
       nav, which is a judgement about this interface rather than about the drawings. -->
  <div class="chat-id">
    <AgentIcon id="ceo" size={26} />
    <div class="grow">
      <h2>{t("ceo.name")}</h2>
      <p class="desc">{t("ceo.role")}</p>
    </div>
    {#if history.length}
      <button class="link" onclick={forget}>{t("mem.forget")}</button>
    {/if}
  </div>

  <!-- Said before the first exchange rather than after a disappointing one: in mock mode the CEO
       echoes, and an operator who does not know that reads the echo as the product being poor. -->
  {#if mockOn}<p class="banner warn small">{t("ceo.mockNote")}</p>{/if}

  {#if history.length === 0}
    <!-- Suggestion chips rather than an empty box: the first move is a thing to click, and a dead
         rectangle with a placeholder in it tells an operator nothing about what to ask. -->
    <div class="chat-log is-empty">
      <!-- The answer to the question an operator who does not know what to do cannot type.
           Derived from the store by `app.guidance`, never generated: a model asked "what should I
           do?" produces a plausible list, and a plausible list is the worst answer here — it can
           name a tab that does not apply or miss the two approvals actually holding the company up.
           Each one is a button because being told to go to Operations and having to find it is two
           steps where the operator asked for one. -->
      {#if (summary?.next_steps ?? []).length}
        <div class="next">
          <p class="next-head">{t("next.title")}</p>
          <p class="muted small centred">{t("next.desc")}</p>
          <ol class="next-list">
            {#each summary.next_steps as step, i (step.key)}
              <li>
                <button
                  class="next-go"
                  onclick={() => goto(step)}
                >
                  <span class="next-rank">{i + 1}</span>
                  <span class="next-what">
                    {step.key.startsWith("ob.") ? t(step.key) : t("next." + step.key)}
                    {#if step.detail}<span class="muted small">· {step.detail}</span>{/if}
                  </span>
                  <span class="next-arrow" aria-hidden="true">→</span>
                </button>
              </li>
            {/each}
          </ol>
        </div>
      {:else}
        <p class="muted centred">{t("next.none")}</p>
      {/if}

      <!-- Suggestion chips rather than an empty box: the first move is a thing to click, and a dead
           rectangle with a placeholder in it tells an operator nothing about what to ask. -->
      <p class="muted centred">{t("ceo.empty")}</p>
      <div class="suggest">
        {#each SUGGESTIONS as key (key)}
          <button disabled={sending} onclick={() => send(t(key))}>{t(key)}</button>
        {/each}
      </div>
    </div>
  {:else}
    <div class="chat-log">
      {#each history as turn, i (turn.ts ?? `optimistic-${i}`)}
        <article class="msg {turn.role === 'user' ? 'user' : 'ceo'}" class:failed={turn.unanswered}>
          <p class="text">{turn.text}</p>
          {#if turn.role === "assistant"}
            <p class="meta">
              <!-- Which model answered, per turn: a conversation can span a tier change or a
                   fallback, and "who said this" is a question about one reply. -->
              {#if turn.provider}{turn.provider}{#if turn.model} / {turn.model}{/if}{/if}
              {#if turn.unanswered}<span class="badge danger">{t("badge.fail")}</span>{/if}
            </p>
          {/if}
        </article>
      {/each}
    </div>
  {/if}

  {#if proposal}
    <!-- The CEO does not execute. It says what it would do; the operator presses the button. -->
    <div class="proposal">
      <p class="small">{t("ceo.proposes")} <strong>{proposal.label}</strong></p>
      <div class="actions">
        <button class="primary" disabled={sending} onclick={accept}>{proposal.label}</button>
        <button onclick={() => (proposal = null)}>{t("ceo.notNow")}</button>
      </div>
    </div>
  {/if}

  <form
    class="composer"
    onsubmit={(e) => {
      e.preventDefault();
      send();
    }}
  >
    <textarea
      rows="3"
      placeholder={t("ceo.placeholder")}
      aria-label={t("ceo.placeholder")}
      value={draft}
      oninput={(e) => (draft = e.currentTarget.value)}
      onkeydown={(e) => {
        // Enter sends, Shift+Enter makes a paragraph. A textarea whose only send is a button costs a
        // reach for the mouse on every question, and this is a conversation.
        if (e.key === "Enter" && !e.shiftKey) {
          e.preventDefault();
          send();
        }
      }}
    ></textarea>
    <button class="primary" type="submit" disabled={sending || !draft.trim()}>{t("ceo.send")}</button>
  </form>
</section>

<style>
  /* The next steps: a numbered list of destinations, not a paragraph of advice. The rank, the thing,
     and an arrow — the arrow is what says "this moves you" rather than "this is true". */
  .next { display: grid; gap: 4px; justify-items: center; width: 100%; max-width: 46rem; }
  .next-head { margin: 0; font-weight: 650; font-size: 15px; }
  .next-list { list-style: none; margin: 8px 0 0; padding: 0; display: grid; gap: 6px; width: 100%; }
  .next-go {
    display: flex;
    align-items: center;
    gap: 11px;
    width: 100%;
    text-align: left;
    padding: 9px 12px;
    border-radius: 9px;
  }
  .next-go:hover:not(:disabled) { border-color: var(--border-ui); background: var(--raised); }
  .next-rank {
    flex: none;
    width: 20px;
    height: 20px;
    display: grid;
    place-content: center;
    border-radius: 999px;
    background: var(--sunken);
    border: 1px solid var(--border);
    font-size: 11px;
    font-weight: 700;
    color: var(--muted);
  }
  .next-what { flex: 1 1 auto; min-width: 0; }
  /* The arrow sits at the far end and only moves on hover, so a column of them is a column rather
     than five arrows at five different x. */
  .next-arrow { flex: none; color: var(--muted); transition: transform var(--t-feedback) var(--ease); }
  .next-go:hover:not(:disabled) .next-arrow { transform: translateX(2px); color: var(--text); }
  /* Only the CEO's own. The card, the chat frame, the bubbles, the chips, the composer and the
     buttons are in `console.css`, because a conversation panel that styles its own buttons is how
     seven tabs came to have seven slightly different ones. */
  .grow { flex: 1; min-width: 0; }
  .centred { text-align: center; margin: 0 0 4px; }
  .text { margin: 0; white-space: pre-wrap; }
  /* The proposal is a decision, so it is separated from the transcript by a rule rather than sitting
     in it as another turn: the CEO said what it would do, and the button belongs to the operator. */
  .proposal { border-top: 1px solid var(--border); padding-top: 12px; display: grid; gap: 10px; }
  .proposal .actions { display: flex; gap: 8px; flex-wrap: wrap; }
  /* No handle. It sat in the corner of the card as a browser artefact; the field already grows to its
     max height on its own, and the panel is not something an operator needs to resize. */
  .composer textarea { resize: none; }
  /* Send inside the field's own gutter. Bottom-aligned beside an 80px textarea it read as a button that
     happened to be next to a box rather than the box's own action. */
  .composer { position: relative; }
  .composer textarea { padding-right: 92px; }
  .composer :global(button) { position: absolute; right: 10px; bottom: 10px; }
  /* Two heights, and which one depends on whether there is a conversation. An empty panel that reserves
     a screen is a screen of nothing: the invitation collapses to the height of its own content, and the
     transcript takes the window once there is something in it. Every review since the first named this
     as the worst thing in the set. */
  /* The panel fills the window whether or not there is a conversation, because a 280px card above 900px
     of background is a page that stops halfway. What made a tall panel read as a void the first time was
     the invitation floating in the middle of it; it is anchored to the composer now (`align-content: end`
     in `console.css`), so the height is a frame rather than a hole. */
  /* The height is in `console.css` now, one rule for both states, and this comment is what two reviews
     disagreeing looks like when both were right.
     The first said an empty transcript reserving 400px above a centred paragraph is a void, so this
     collapsed the card when there was nothing to read. The second said the collapsed card leaves the
     *page* ending in 300px of background above a floating footer — the most unfinished route in the
     product. Both are true, and the fix neither of them named is to stop the empty state floating:
     the invitation is anchored to the composer (`align-content: end`), so a tall card is a frame
     around a conversation that has not started rather than a hole above one. The note above claimed
     that anchoring was already done. It was not — `.chat-log.is-empty` still centred. */
  /* The empty log no longer needs a floor: the card is sized to the page now, so this row is
     whatever is left between the identity strip and the composer. A fixed 220px on top of that
     was what pushed the composer down and left the suggestions floating in the middle. */
</style>
