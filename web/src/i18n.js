/**
 * The interface strings, imported as data.
 *
 * `web/i18n/*.json` is the source of truth and the shipped single-file page carries a generated
 * copy of it; `tests/test_i18n.py` fails if the two disagree.
 *
 * **English is in the bundle and every other language is fetched.** That is not a size trick, it
 * follows the lookup's own contract:
 *
 *     TABLES[lang]?.[key] ?? TABLES.en[key] ?? key
 *
 * English is the fallback for every key in every language, so it is needed unconditionally; French
 * is needed only when French is chosen. Measured on the first build that inlined both: 91 132 bytes
 * of bundle, of which 57 325 were the two tables — 63%, half of it a language most operators never
 * select.
 *
 * The chosen table is awaited **before the first paint** (see `main.js`), so a French operator never
 * sees English flash past. That is the whole reason `load` exists rather than a `$effect` that
 * swaps the strings in once they arrive.
 *
 * The key is the last resort on purpose: a label reading `docs.folder` on screen is ugly and
 * unmistakable, where a blank would look like a bug in the layout.
 */
import en from "../i18n/en.json";

export const TABLES = { en };

// The languages that are fetched, one explicit loader each. **Not** a template literal over a
// variable: `import(`../i18n/${lang}.json`)` makes the bundler include every match, so `en` ended
// up in both the static graph and a dynamic chunk and Rollup said so. A map states which tables are
// loaded and which one is the base, which is the fact anyway — adding a language is one line here.
const LOADERS = {
  fr: () => import("../i18n/fr.json"),
};

// Every language this console can be in: the base, plus the ones with a loader.
export const LANGUAGES = ["en", ...Object.keys(LOADERS)];

/** The language to start in: the query string, then what was chosen last, then the browser's. */
export function pick(search, stored, navigatorLanguage) {
  const asked = new URLSearchParams(search).get("lang");
  for (const candidate of [asked, stored, (navigatorLanguage || "en").slice(0, 2)]) {
    if (candidate && LANGUAGES.includes(candidate)) return candidate;
  }
  return "en";
}

/**
 * Make sure a language's table is loaded. Idempotent, and safe to call for `en`.
 *
 * A failed fetch is swallowed to a warning rather than thrown: the console still works in English,
 * which is a far better answer than a blank page because a chunk did not arrive.
 */
export async function load(lang) {
  if (TABLES[lang] || !LOADERS[lang]) return;
  try {
    const table = await LOADERS[lang]();
    TABLES[lang] = table.default ?? table;
  } catch (e) {
    console.warn(`corparius: could not load the ${lang} strings, staying in English`, e);
  }
}

export function translator(lang) {
  return (key) => TABLES[lang]?.[key] ?? TABLES.en[key] ?? key;
}
