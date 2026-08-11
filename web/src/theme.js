/**
 * The operator's theme, applied at boot rather than when a particular tab happens to mount.
 *
 * The bug this exists to fix, found in a screenshot: `applyTheme` lived inside `Settings.svelte`, so
 * an operator who had chosen light got **dark on every tab until they opened Settings** — and then
 * light everywhere, which looks like the console changing its mind. The theme is stored on this
 * corparius rather than in the browser precisely so it follows the operator between machines; loading
 * it anywhere but the shell throws that away.
 *
 * `tokens.css` keys light off `[data-theme="light"]` and treats `:root` as dark, so the attribute has
 * to be written for light to happen at all. Hue and chroma are two custom properties on the root, and
 * an unset one is removed rather than set to a default: the stylesheet's own value is the default.
 */
import { get } from "./api.js";

export function applyTheme(theme) {
  const root = document.documentElement;
  if (theme?.mode) root.setAttribute("data-theme", theme.mode);
  else root.removeAttribute("data-theme");
  for (const [name, key] of [
    ["--ui-hue", "hue"],
    ["--ui-chroma", "chroma"],
  ]) {
    if (theme?.[key]) root.style.setProperty(name, theme[key]);
    else root.style.removeProperty(name);
  }
}

/**
 * Read it and apply it. Failure is silent on purpose: a console that refuses to render because it
 * could not learn a colour preference would be worse than one that renders in the default.
 */
export async function loadTheme(token) {
  try {
    const theme = await get("/api/theme", { token, revalidate: false });
    applyTheme(theme);
    return theme;
  } catch {
    return null;
  }
}
