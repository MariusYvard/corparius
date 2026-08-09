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
// `base` is relative, so the bundle does not care what path it is served under. The console is
// served from `/app/` today; a relative base means that can change without a rebuild, and it means
// the same bundle opens from `file://` when someone wants to look at it.
export default defineConfig({
  plugins: [svelte()],
  base: "./",
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
