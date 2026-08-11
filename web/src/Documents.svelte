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

  let { lang, company, token = "" } = $props();
  let t = $derived(translator(lang));

  let inventory = $state(null);
  let failure = $state(null);
  let reading = $state(null);
  let outcomes = $state([]);
  let sending = $state("");
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

  $effect(() => {
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
    <p class="tally">
      {fill(t("docs.head"), {
        n: inventory.total,
        r: inventory.reaching,
        u: inventory.used,
        b: inventory.budget,
      })}
    </p>

    <div class="rows">
    {#each inventory.documents as doc (doc.path)}
      <article class="row" class:reaches={doc.reaches}>
        <div>
          <strong>{doc.path}</strong>
          <span class="badge">{t(doc.written ? "docs.written" : "docs.dropped")}</span>
          <!-- The one state the product had no way of saying out loud: readable, on file, and past
               the budget, so no agent ever reads it. `docs.why.cut` carries the two numbers. -->
          <p class="why muted small">
            {#if doc.reason === "cut"}
              {fill(t("docs.why.cut"), { n: doc.chars ?? 0, total: doc.total ?? 0 })}
            {:else if doc.reason}
              {t("docs.why." + doc.reason)}
            {/if}
          </p>
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
      <p class="empty">{t("docs.none")}</p>
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
  /* Only what Documents has. The dropzone, the card, the rows, the badges and the buttons are the
     console's language and live in `console.css`. */
  .outcome { font-size: 13px; color: var(--ok); margin: 0; }
  .outcome.bad { color: var(--danger); }
  .tally { font-size: 14px; margin: 0; }
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
