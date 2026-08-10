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

  let { lang, company, token = "" } = $props();
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

  $effect(() => {
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
      const done = await post("/api/v1/chat", { message }, { token });
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
      await post("/api/v1/chat/forget", {}, { token });
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

<section class="card">
  <div class="head">
    <div>
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
    <p class="muted">{t("ceo.empty")}</p>
    <div class="actions">
      {#each SUGGESTIONS as key (key)}
        <button class="quiet" disabled={sending} onclick={() => send(t(key))}>{t(key)}</button>
      {/each}
    </div>
  {:else}
    <div class="log">
      {#each history as turn, i (turn.ts ?? `optimistic-${i}`)}
        <article class="turn {turn.role}">
          <p class="text">{turn.text}</p>
          {#if turn.role === "assistant"}
            <p class="who muted small">
              <!-- Which model answered, per turn: a conversation can span a tier change or a
                   fallback, and "who said this" is a question about one reply. -->
              {#if turn.provider}{turn.provider}{#if turn.model} / {turn.model}{/if}{/if}
              {#if turn.unanswered}<span class="chip danger">{t("badge.fail")}</span>{/if}
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
        <button disabled={sending} onclick={accept}>{proposal.label}</button>
        <button class="quiet" onclick={() => (proposal = null)}>{t("ceo.notNow")}</button>
      </div>
    </div>
  {/if}

  <form
    class="ask"
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
    <button type="submit" disabled={sending || !draft.trim()}>{t("ceo.send")}</button>
  </form>
</section>

<style>
  /* Tokens only; `tests/test_console_tokens.py` asserts it. */
  .card {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 1rem 1.1rem;
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
  .log { display: grid; gap: 0.7rem; margin: 0 0 1rem; }
  .turn { padding: 0.6rem 0.8rem; border-radius: 10px; max-width: 44rem; }
  /* The operator's own words sit to the right and in the raised surface; the CEO's fill the width.
     Position carries the speaker, so the transcript is readable without a label per line. */
  .turn.user { background: var(--raised); border: 1px solid var(--border-ui); margin-left: auto; }
  .turn.assistant { background: var(--accent-soft); border: 1px solid var(--border); }
  .text { margin: 0; white-space: pre-wrap; }
  .who { margin: 0.3rem 0 0; }
  .proposal { border-top: 1px solid var(--border); padding-top: 0.7rem; margin-bottom: 0.7rem; }
  .ask { display: grid; gap: 0.5rem; }
  .ask button { justify-self: end; }
  textarea {
    background: var(--raised);
    color: var(--text);
    border: 1px solid var(--border-ui);
    border-radius: 8px;
    padding: 0.5rem 0.6rem;
    font: inherit;
    resize: vertical;
  }
  .actions { display: flex; gap: 0.4rem; flex-wrap: wrap; align-items: center; }
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
  button.link { background: none; border: 0; color: var(--accent); text-decoration: underline; padding: 0.2rem 0; }
  button:disabled { opacity: 0.45; cursor: default; }
  button:focus-visible, textarea:focus-visible { outline: 2px solid var(--select); outline-offset: 2px; }
  .muted { color: var(--muted); }
  .small { font-size: 0.86rem; }
  .banner { padding: 0.6rem 0.85rem; border-radius: 8px; margin: 0 0 1rem; border: 1px solid; }
  .banner.danger { border-color: var(--danger); background: var(--danger-soft); color: var(--danger); }
  .banner.warn { border-color: var(--warn); background: var(--warn-soft); color: var(--warn); }
  .banner.ok { border-color: var(--ok); background: var(--ok-soft); color: var(--ok); }
  .chip {
    border: 1px solid var(--border-ui);
    border-radius: 999px;
    padding: 0 0.45rem;
    font-size: 0.76rem;
  }
  .chip.danger { color: var(--danger); border-color: var(--danger); }
</style>
