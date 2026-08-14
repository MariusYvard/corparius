<script>
  /**
   * One pending approval, rendered the same way wherever it appears.
   *
   * ## Why this is a component
   *
   * The same two requests were drawn twice, differently. Overview gave each one a tool name, a plain
   * sentence and three buttons; Operations gave it a risk chip, a "Learn more" disclosure, five facts
   * and a note field. A review put the cost plainly: *"Same object, same data, two designs — the user
   * learns the component twice and will distrust which one is authoritative."*
   *
   * And the drift had already cost something concrete. The short form was **dropping the risk chip**,
   * which is the only thing that tells a spend from a read — so the surface an operator meets first
   * was the one that could not say whether pressing Approve sends an email or reads a file. That is
   * not a styling difference; approving blind is not approving.
   *
   * ## What `compact` does and does not change
   *
   * It changes **how much explanation** is on screen, never the decision. Identical in both:
   *
   *   * the tool name, the risk chip, and who asked;
   *   * what the tool does, in the core's own words (`detail.does` — built server-side precisely so
   *     two clients cannot render two different explanations);
   *   * the three actions, at the three weights they have earned: `Approve` filled, `Approve, stop
   *     asking` as warm text because it grants a standing rule and never asks again, `Reject` as
   *     quiet danger.
   *
   * Only in the full form: why this one stopped, what the risk tier means, what yes and no each do,
   * the draft itself, and a note. An operator clearing a familiar queue wants the buttons; one
   * meeting an unfamiliar tool wants the paragraph. Both are worth having — what is not worth having
   * is two components that disagree about which is which.
   */
  import { translator } from "./i18n.js";

  let {
    approval,
    lang,
    busy = "",
    compact = false,
    onDecide,
  } = $props();
  let t = $derived(translator(lang));

  // Local, because it is a reading state rather than a company one: which panel this operator has
  // open right now has no business travelling to the server or up to a parent.
  let open = $state(false);
  let note = $state("");

  const decide = (decision, remember = "") =>
    onDecide?.(approval.id, decision, remember, note);
</script>

<article class="row" class:block={!compact}>
  <div class="grow">
    <header class="ap-head">
      <strong>{approval.tool}</strong>
      <span class="badge risk {approval.risk}">{t("risk." + approval.risk)}</span>
      <span class="muted small">· {t("ops.requestedBy")} {approval.agent}</span>
    </header>
    <!-- **The payload, not the verb.** A review named this as the single biggest thing holding the
         product back and it was right about the product, not the styling: the card led with
         `detail.does` — "Sends the drafted messages to the selected targets" — which is what the tool
         does *in general*. What is about to happen was one disclosure away. Being asked to press
         Approve on a verb is not consent.
         The core already computed all of it. `detail.draft` is the concrete thing ("Replace the
         two-tier page with one single-seat plan at 19 a month") and `parameters` are the values it
         will run with. The console was reading the wrong field. -->
    {#if approval.detail?.draft}
      <p class="ap-draft">{approval.detail.draft}</p>
    {/if}
    {#if Object.keys(approval.parameters ?? {}).length}
      <p class="ap-params">
        {#each Object.entries(approval.parameters) as [name, value] (name)}
          <span class="ap-param"><span class="muted">{name}</span> <strong>{value}</strong></span>
        {/each}
      </p>
    {/if}
    {#if approval.detail?.does}<p class="desc">{approval.detail.does}</p>{/if}

    {#if !compact}
      <button class="link" aria-expanded={open} onclick={() => (open = !open)}>
        {t("ops.more")}
      </button>
      {#if open}
        <dl class="detail">
          {#if approval.detail?.why}
            <dt>{t("ops.whyStopped")}</dt><dd>{approval.detail.why}</dd>
          {/if}
          <dt>{t("ops.riskMeans")}</dt><dd>{approval.detail?.risk_means}</dd>
          <dt>{t("ops.ifYes")}</dt><dd>{approval.detail?.on_approve}</dd>
          <dt>{t("ops.ifNo")}</dt><dd>{approval.detail?.on_reject}</dd>
        </dl>
      {/if}

      <label class="note">
        <span class="muted">{t("ops.note")}</span>
        <input bind:value={note} />
      </label>
    {/if}
  </div>

  <div class="actions">
    <button class="primary" disabled={busy === approval.id} onclick={() => decide("approved")}>
      {t("btn.approve")}
    </button>
    {#if approval.can_remember}
      <button
        class="link standing"
        disabled={busy === approval.id}
        onclick={() => decide("approved", "always")}
      >{t("ops.always")}</button>
    {/if}
    <button class="danger-quiet" disabled={busy === approval.id} onclick={() => decide("rejected")}>
      {t("btn.reject")}
    </button>
  </div>
</article>

<style>
  /* The header wraps as a unit: tool, risk and requester are one clause, and a risk chip that wrapped
     away from the tool name it qualifies is the one thing here that must not happen. */
  .ap-head { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
  /* What is about to happen, at reading size. This is the sentence somebody is consenting to, so it
     outranks the tool's own description of itself, which is now the small grey line under it. */
  .ap-draft { margin: 6px 0 0; font-size: 14px; line-height: 1.55; max-width: 68ch; }
  /* The values it will run with, as pairs. `price 19` is the fact an operator checks before pressing
     Approve, and it was inside a JSON blob nothing rendered. */
  .ap-params { display: flex; flex-wrap: wrap; gap: 4px 16px; margin: 6px 0 0; font-size: 12.5px; }
  .ap-param { display: inline-flex; gap: 6px; align-items: baseline; white-space: nowrap; }
  .ap-param strong { font-variant-numeric: tabular-nums; }
</style>
