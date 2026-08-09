/**
 * The v1 client. One place that knows how to talk to a corparius core.
 *
 * Three things it does that the old page's `api()` did not, and each one exists because stage 8
 * built the other side of it:
 *
 *   * it reads the **error envelope**: a v1 refusal is `{error: {code, message, detail}}`, so a
 *     caller can branch on `code` instead of matching a sentence that gets reworded. The thrown
 *     error carries the code and the detail rather than flattening both into a string.
 *   * it sends `Authorization: Bearer` when it has a device credential, and `X-Corp-Token` when it
 *     has the shared bootstrap one. The core accepts either; which one this client holds depends on
 *     whether it was paired.
 *   * it honours **ETags**. Every v1 GET carries one and an unchanged resource answers 304 with no
 *     body, so a poller that keeps the validator re-downloads nothing. `/api/v1/summary` is 2 859
 *     bytes against the 48 530 the old page polled every five seconds; this is what makes the
 *     unchanged bytes free on the wire.
 */
const validators = new Map();
const cached = new Map();

export class Refused extends Error {
  constructor(status, body) {
    const error = body?.error ?? {};
    super(error.message || `HTTP ${status}`);
    this.status = status;
    this.code = typeof error === "object" ? (error.code ?? "") : "";
    this.detail = error.detail ?? {};
  }
}

export function credential(token) {
  // A device credential starts with `corp_` (see `kernel/tokens.py`); anything else is the shared
  // bootstrap token, which the page has always sent as `X-Corp-Token`.
  if (!token) return {};
  return token.startsWith("corp_")
    ? { Authorization: `Bearer ${token}` }
    : { "X-Corp-Token": token };
}

export async function get(path, { token = "", revalidate = true } = {}) {
  const headers = { ...credential(token) };
  const seen = validators.get(path);
  if (revalidate && seen) headers["If-None-Match"] = seen;
  const res = await fetch(path, { headers });
  if (res.status === 304) return cached.get(path);
  const body = res.status === 204 ? null : await res.json();
  if (!res.ok) throw new Refused(res.status, body);
  const tag = res.headers.get("ETag");
  if (tag) {
    validators.set(path, tag);
    cached.set(path, body);
  }
  return body;
}

export async function post(path, payload, { token = "", idempotencyKey = "" } = {}) {
  const headers = { "Content-Type": "application/json", ...credential(token) };
  if (idempotencyKey) headers["Idempotency-Key"] = idempotencyKey;
  const res = await fetch(path, { method: "POST", headers, body: JSON.stringify(payload ?? {}) });
  const body = await res.json();
  if (!res.ok || body?.ok === false) throw new Refused(res.status, body);
  return body;
}

/** For tests and for a hard refresh: forget every validator so the next GET fetches in full. */
export function forget() {
  validators.clear();
  cached.clear();
}
