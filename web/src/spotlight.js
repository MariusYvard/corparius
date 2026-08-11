/**
 * The cursor's position, as two custom properties on whichever card it is over.
 *
 * One listener on the document rather than one per card, and it is not a micro-optimisation: cards
 * mount and unmount on every tab change and every poll, so per-card listeners would have to be
 * attached and torn down by eight components, and the one that forgot would leak a handler per
 * refresh. This attaches once, at boot, and cannot go out of step with the DOM.
 *
 * Percentages rather than pixels so the gradient does not need to know the card's size, and written
 * only while the pointer is inside a card — the effect itself is drawn by `.card:hover::after`, so
 * doing anything outside one would be work nobody can see.
 */
export function trackSpotlight(root = document) {
  let last = null;
  root.addEventListener(
    "pointermove",
    (event) => {
      // A fine pointer only. On a touchscreen every tap would light a card and leave it lit, which
      // reads as a selection the operator did not make.
      if (event.pointerType !== "mouse") return;
      const card = event.target instanceof Element ? event.target.closest(".card") : null;
      if (card !== last && last) last.style.removeProperty("--mx");
      last = card;
      if (!card) return;
      const box = card.getBoundingClientRect();
      if (!box.width || !box.height) return;
      card.style.setProperty("--mx", `${((event.clientX - box.left) / box.width) * 100}%`);
      card.style.setProperty("--my", `${((event.clientY - box.top) / box.height) * 100}%`);
    },
    { passive: true },
  );
}
