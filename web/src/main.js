// The measured oklch ramps, ported verbatim from the shipped page. Imported here so they are
// in the bundle rather than a second request, and so every component can only use tokens.
import "./tokens.css";
// And the component layer on top of them. Tokens are a palette, not a design: the first pass shipped
// the ramps without this and the result was seven tabs of identical rectangles.
import "./console.css";
import { mount } from "svelte";
import App from "./App.svelte";
import { load, pick } from "./i18n.js";
import { trackSpotlight } from "./spotlight.js";

// The chosen language's strings are awaited before the first paint, so a French operator does not
// watch English flash past. English is already in the bundle, so this resolves immediately for it.
const lang = pick(location.search, localStorage.getItem("corparius-lang"), navigator.language);
await load(lang);

trackSpotlight();

export default mount(App, { target: document.getElementById("app"), props: { lang } });
