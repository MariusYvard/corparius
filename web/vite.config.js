import { svelte } from "@sveltejs/vite-plugin-svelte";
import { defineConfig } from "vite";

// The console's build. Two things here are load-bearing and both are about how corparius ships.
//
// `outDir` writes **inside the package**, at `corparius/api/static/`. That is the same decision
// `webui.html` already embodies: a resource that lives inside `corparius/` is found by
// `paths._resource("corparius", ...)` in all three distribution modes — source checkout, frozen
// binary (sys._MEIPASS), pip-installed wheel — with no fallback and no per-mode special case.
// Anything written beside the package instead would need the `_data/` fallback that `companies/`
// and `plugins/` need, for no gain.
//
// `base` is `/app/` — absolute, and it was relative until the console became the default one. A
// relative base sounds strictly more flexible and is the opposite here: the shell is now served
// from **two** paths, `/` and `/app/`, and a relative `./console.js` resolves against whichever one
// the browser asked for, so the copy served at `/` requested `/console.js` and got a 404 — a blank
// page with a 200. An absolute base means the assets are at `/app/` no matter where the shell is
// served from, which is what makes serving it from more than one path possible at all.
//
// The claim that went with the old value — that a relative base lets the bundle open from
// `file://` — was never exercised by a test, and could not have been: this is an ES module that
// dynamic-imports the French chunk, and a browser refuses module loads over `file://`.
// The dev server's proxy, which `web/README.md` has promised since this folder existed and which
// was never here. Without it `npm run dev` serves the console and every `/api/...` call it makes
// goes to Vite, which answers its own 404 page — so the console renders and then reports that it
// cannot reach the core, on a machine where the core is running fine.
//
// Measured while changing `base`: Vite's dev server redirects `/` to `/app/` on its own, so the two
// addresses behave the same in development as in production without any config for it.
const CORE = `http://127.0.0.1:${process.env.CORP_UI_PORT || 8600}`;

export default defineConfig({
  plugins: [svelte()],
  base: "/app/",
  server: {
    // `/site` is here because the Sales-site card renders the generated site in an iframe, and a
    // preview that 404s in development is the kind of thing that gets "fixed" in the component.
    proxy: { "/api": CORE, "/site": CORE },
  },
  build: {
    outDir: "../corparius/api/static",
    emptyOutDir: true,
    // No hashed names. The server sends `Cache-Control: no-store` for the shell and the operator
    // may be looking at a build from five minutes ago; a stable name is what lets a hard refresh
    // be the whole remedy. There is one client and it is on loopback — cache-busting by filename
    // buys nothing and costs a directory listing that changes every build.
    rollupOptions: {
      output: {
        entryFileNames: "console.js",
        chunkFileNames: "console-[name].js",
        assetFileNames: "console.[ext]",
      },
    },
    // Measured in the commit that added this: the whole console shell is ~14 KB gzipped, so a
    // warning at 500 KB would never fire and a low one says what the budget actually is.
    chunkSizeWarningLimit: 200,
  },
});
