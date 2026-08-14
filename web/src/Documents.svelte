<script>
  /**
   * The third tab: what the company has on file, and what of it an agent actually reads.
   *
   * The number that matters is not how many files exist. `reaching` against `total`, `used` against
   * `budget` — a company holding twelve documents can be feeding two of them to its agents while the
   * other ten sit there looking like knowledge. Nothing in the product said so before the inventory
   * resource existed, and the badge on each row is where an operator finds out which state a file is
   * in: reaching the prompt, cut short, past the budget, or unreadable at all.
   *
   * ## Not polled, and that is a rule rather than a preference
   *
   * `inventory` opens and extracts every file it lists — PDF, docx, xlsx, csv. Putting that on a five
   * second timer is the same mistake as a network probe on a polled endpoint, which this project
   * banned after `/api/providers` opened a socket on every refresh. So this tab loads on arrival, on
   * a company change, and when somebody presses the button. Nothing here has an interval.
   *
   * ## A refused file is not a failed request
   *
   * Asking to store a `.zip` is a well-formed thing to ask. The answer is `stored: false` with a
   * `reason` code, which is why one drop of seven files can report six stored and one skipped instead
   * of a banner saying the upload failed. Each reason has its own string — `docs.refused.too-large`,
   * `docs.refused.no-extractor` — so the operator learns which file and why.
   *
   * One file per request, deliberately: a batch would collapse seven outcomes into one answer and
   * make per-file progress something this page invented.
   */
  import { get, post, Refused } from "./api.js";
  import { fill, translator } from "./i18n.js";
  import Empty from "./Empty.svelte";

  let { lang, company, token = "", active = true } = $props();
  let t = $derived(translator(lang));

  let inventory = $state(null);
  let failure = $state(null);
  let reading = $state(null);
  let outcomes = $state([]);
  let sending = $state("");
  // Which file has its full outline open. One at a time: five headings is enough to say
  // what a file is, and a page of every heading of every file is the wall the index was
  // built to replace.
  let openDoc = $state("");
  let over = $state(false);
  let copied = $state(false);

  const q = () => `company=${encodeURIComponent(company)}`;

  async function load() {
    try {
      inventory = await get(`/api/v1/documents?${q()}`, { token });
      failure = null;
    } catch (e) {
      failure = e instanceof Refused ? e : new Refused(0, { error: { message: String(e) } });
    }
  }

  // `active` is **read**, not required. Read, so coming back to a kept panel reloads rather than
  // showing an inventory from an hour ago. Not required, because `App.svelte` builds a panel on
  // hover — a fetch that waited for the click would leave the prefetch prefetching nothing.
  $effect(() => {
    active;
    if (company) load();
  });

  /** base64 without a data: prefix, which is what the endpoint decodes with `validate=True`. */
  function encode(file) {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onerror = () => reject(reader.error);
      reader.onload = () => resolve(String(reader.result).split(",")[1] ?? "");
      reader.readAsDataURL(file);
    });
  }

  async function send(files) {
    outcomes = [];
    for (const file of Array.from(files)) {
      sending = file.name;
      try {
        const done = await post(
          "/api/v1/documents",
          { name: file.name, data: await encode(file), company },
          { token },
        );
        // The refreshed inventory rides back with every answer, so the card is the folder as it now
        // stands rather than as it was — and a seven-file drop does not need seven extra reads.
        inventory = done;
        outcomes = [...outcomes, done];
      } catch (e) {
        failure = e instanceof Refused ? e : new Refused(0, { error: { message: String(e) } });
      }
    }
    sending = "";
  }

  async function remove(path) {
    sending = path;
    try {
      const done = await post("/api/v1/documents/delete", { path, company }, { token });
      inventory = done;
      outcomes = [done];
      if (reading?.path === path) reading = null;
    } catch (e) {
      failure = e;
    } finally {
      sending = "";
    }
  }

  async function read(path) {
    reading = null;
    try {
      // The whole extracted text, with no prompt budget applied. The row's badge says "first 4000 of
      // 12000" and is honest; it is still the wrong answer for a person rereading their own brief,
      // who used to have to go and open the file.
      reading = await get(`/api/v1/documents/text?${q()}&path=${encodeURIComponent(path)}`, { token });
      copied = false;
    } catch (e) {
      failure = e;
    }
  }

  async function copy(text) {
    try {
      await navigator.clipboard.writeText(text);
      copied = true;
    } catch {
      // No clipboard permission is not worth a banner: the text is on screen and selectable.
      copied = false;
    }
  }

  function onDrop(event) {
    event.preventDefault();
    over = false;
    if (event.dataTransfer?.files?.length) send(event.dataTransfer.files);
  }

  /** One outcome as a sentence. Every hole is filled from the answer, never from what was sent. */
  function outcomeLine(done) {
    if (done.removed) return fill(t("docs.removed"), { name: done.trashed });
    if (done.stored === false) {
      return fill(t("docs.refused." + done.reason), {
        name: done.name,
        detail: done.detail ?? "",
        mb: Math.round((inventory?.max_upload ?? 0) / (1 << 20)),
      });
    }
    if (done.stored) {
      const key = done.replaced ? "docs.replaced" : "docs.stored";
      return fill(t(key), { name: done.name });
    }
    if (done.removed === false) return fill(t("docs.refused." + done.reason), { name: done.detail ?? "" });
    return "";
  }

  let megabytes = $derived(Math.round((inventory?.max_upload ?? 0) / (1 << 20)));
</script>

{#if failure}
  <p class="banner danger">
    {failure.message}
    {#if failure.code}<code>{failure.code}</code>{/if}
  </p>
{/if}

<section class="card">
  <h2>{t("docs.dropTitle")}</h2>
  <p class="desc">{t("docs.dropDesc")}</p>

  <!-- svelte-ignore a11y_no_static_element_interactions -->
  <div
    class="dropzone"
    class:over
    ondragover={(e) => {
      e.preventDefault();
      over = true;
    }}
    ondragleave={() => (over = false)}
    ondrop={onDrop}
  >
    <p class="dropzone-line">{t("docs.dropHere")}</p>
    <p class="dropzone-pick">
      <span class="muted">{t("docs.dropOr")}</span>
      <!-- A label bound to a clipped input, not a button calling `.click()`: the label *is* the
           accessible control and works from the keyboard without any script.

           The input comes **first** in the DOM so `input:focus-visible + .filebtn` can draw the focus
           ring on the label. It read the other way round at first, and Svelte's CSS pass said the
           selector was unused — a focus ring nobody could see, which is the whole point of having
           one. Order is invisible here because the input is clipped, not hidden. -->
      <input
        id="doc-file"
        type="file"
        multiple
        accept={(inventory?.accepts ?? []).join(",")}
        onchange={(e) => e.currentTarget.files && send(e.currentTarget.files)}
      />
      <label class="filebtn" for="doc-file">{t("docs.dropPick")}</label>
    </p>
    {#if inventory}
      <!-- The limits from the one place that decides them. A second copy in this file would be a
           promise the server breaks. -->
      <p class="muted small">
        {fill(t("docs.accepts"), { list: inventory.accepts.join(" "), mb: megabytes })}
      </p>
    {/if}
    {#if sending}<p class="muted small">{fill(t("docs.sending"), { name: sending })}</p>{/if}
  </div>

  {#each outcomes as done, i (i)}
    <p class="outcome" class:bad={done.stored === false || done.removed === false}>
      {outcomeLine(done)}
    </p>
  {/each}
</section>

<section class="card">
  <div class="card-head">
    <div>
      <h2>{t("docs.title")}</h2>
      <p class="desc">{t("docs.desc")}</p>
    </div>
    <button onclick={load}>{t("docs.reload")}</button>
  </div>

  {#if !inventory}
    <p class="muted">{t("docs.reading")}</p>
  {:else}
    <!-- Three readouts and a meter. It was one sentence carrying four numbers — "0 on file · 0 reach
         the agents · 0 of 6000 characters used" — which is a debug line, not a report. The full
         sentence stays as the meter's label, so nothing is lost for a screen reader. -->
    <div class="pulse-row">
      <div class="stat">
        <div class="label">{t("docs.onFile")}</div>
        <div class="value">{inventory.total}</div>
      </div>
      <div class="stat">
        <div class="label">{t("docs.reaching")}</div>
        <div class="value">{inventory.reaching}</div>
      </div>
      <!-- What the index found. "Reach the agents" used to be a smaller number than "on file",
           because the block was the newest files that fit; every readable file reaches them now, so
           the number that carries information is how many *parts* they were resolved into. -->
      <div class="stat">
        <div class="label">{t("docs.sections")}</div>
        <div class="value">{inventory.sections ?? 0}</div>
      </div>
      <div class="stat budget">
        <div class="label">{t("docs.budget")}</div>
        <div class="value">
          {inventory.used.toLocaleString(lang)}
          <span class="of">/ {inventory.budget.toLocaleString(lang)}</span>
        </div>
        <span
          class="bar"
          role="img"
          aria-label={fill(t("docs.head"), {
            n: inventory.total,
            r: inventory.reaching,
            u: inventory.used,
            b: inventory.budget,
          })}
        >
          <i style="width: {Math.min(100, Math.round((inventory.used / Math.max(1, inventory.budget)) * 100))}%"></i>
        </span>
      </div>
    </div>

    <div class="rows">
    {#each inventory.documents as doc (doc.path)}
      <article class="row" class:reaches={doc.reaches}>
        <div>
          <strong>{doc.path}</strong>
          <span class="badge">{t(doc.written ? "docs.written" : "docs.dropped")}</span>
          <!-- Every state is a plain lookup now. `docs.why.cut` — "reaches the agents: first {n} of
               {total} characters" — was the only one that interpolated, and it is gone with the
               state it described: `load` reads whole files so the index can map them, so no
               document is truncated on the way to a prompt any more. It is the second string this
               tab has *lost* rather than gained, after `docs.why.budget`, and both for the same
               reason — a translated sentence for an unreachable state describes a product that no
               longer exists. -->
          <p class="why muted small">
            {#if doc.reason}{t("docs.why." + doc.reason)}{/if}
          </p>
          <!-- The outline, which is the thing an agent actually navigates by. It answers the question
               this tab could not answer before — "what is *in* that file" — without opening it, and
               it is the same list the index puts in front of every prompt. -->
          {#if doc.kind === "text"}
            {#if (doc.sections ?? []).length}
              <ol class="outline">
                {#each doc.sections.slice(0, openDoc === doc.path ? doc.sections.length : 5) as part (part.line)}
                  <li style="padding-left: {Math.min(part.level - 1, 3) * 12}px">
                    <span class="o-title">{part.title}</span>
                    <span class="o-size muted">{part.chars.toLocaleString(lang)}</span>
                  </li>
                {/each}
              </ol>
              {#if doc.sections.length > 5}
                <button class="link" onclick={() => (openDoc = openDoc === doc.path ? "" : doc.path)}>
                  {openDoc === doc.path
                    ? t("col.less")
                    : fill(t("col.more"), { n: doc.sections.length - 5 })}
                </button>
              {/if}
            {:else}
              <p class="muted small">{t("docs.noHeadings")}</p>
            {/if}
          {/if}
        </div>
        <div class="actions">
          <button class="link" onclick={() => read(doc.path)}>{t("docs.read")}</button>
          <button class="danger-quiet" disabled={sending === doc.path} onclick={() => remove(doc.path)}>
            {t("docs.remove")}
          </button>
        </div>
      </article>
    {/each}
    </div>

    {#if inventory.documents.length === 0}
      <!-- The sentence says "into the folder below", so the folder goes below it. It was printed above,
           which made the one instruction on an empty tab point the wrong way. -->
      <Empty text={t("docs.none")} />
      <p class="folder muted small">
        <span>{t("docs.folder")}:</span>
        <code class="path" title={inventory.folder}>{inventory.folder}</code>
      </p>
    {:else if inventory.total > inventory.documents.length}
      <p class="muted small">
        {fill(t("docs.more"), { n: inventory.total - inventory.documents.length })}
      </p>
    {/if}
  {/if}
</section>

{#if reading}
  <section class="card">
    <div class="card-head">
      <div>
        <h2>{reading.path}</h2>
        <p class="desc">{fill(t("docs.readAll"), { n: reading.text.length })}</p>
      </div>
      <div class="actions">
        <button class="quiet" onclick={() => copy(reading.text)}>
          {copied ? t("docs.copied") : t("docs.copy")}
        </button>
        <button class="link" onclick={() => (reading = null)}>{t("task.cancel")}</button>
      </div>
    </div>
    <pre class="read">{reading.text}</pre>
  </section>
{/if}

<style>
  /* The outline. Indented by heading level, with each section's size at the end — an operator judging
     whether a file is worth keeping wants "how big is the pricing part", not "how big is the file".
     A list rather than chips: these are ordered, and the order is the document. */
  .outline { list-style: none; margin: 6px 0 0; padding: 0; display: grid; gap: 1px; }
  .outline li {
    display: flex;
    align-items: baseline;
    gap: 10px;
    font-size: 12.5px;
    padding: 2px 0;
    min-width: 0;
  }
  .o-title { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  /* The count sits at the far end so a column of them reads as a column. */
  .o-size { margin-left: auto; font-variant-numeric: tabular-nums; font-size: 11.5px; flex: none; }
  /* Only what Documents has. The dropzone, the card, the rows, the badges and the buttons are the
     console's language and live in `console.css`. */
  .outcome { font-size: 13px; color: var(--ok); margin: 0; }
  .outcome.bad { color: var(--danger); }
  .stat.budget { min-width: 190px; }
  .stat.budget .bar { margin-top: 7px; }
  .folder { display: flex; gap: 6px; align-items: baseline; flex-wrap: wrap; overflow-wrap: anywhere; }
  /* A file past the prompt budget is dimmed rather than hidden: it is on disk, it is readable, and
     nothing reads it — which is a fact the operator needs, not one to tidy away. */
  .row:not(.reaches) strong { color: var(--muted); }
  .why { margin: 3px 0 0; }
  .read { white-space: pre-wrap; background: var(--raised); border: 1px solid var(--border);
    border-radius: 10px; padding: 12px 14px; font-size: 13.5px; max-height: 60vh; overflow: auto; }
  /* Clipped, never `display: none`: the label is the control, and hiding the input would take the
     whole tab out of the keyboard's reach. */
  input[type="file"] {
    position: absolute;
    width: 1px;
    height: 1px;
    opacity: 0;
    pointer-events: none;
  }
</style>
