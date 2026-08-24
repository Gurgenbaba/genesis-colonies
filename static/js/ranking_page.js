(() => {
  "use strict";

  const root = document.getElementById("ranking-page");
  if (!root) return;

  const focusClass = "gc-ranking-focus";
  const tableRoot = document.getElementById("ranking-table-content");
  const myStrip = document.getElementById("ranking-my-strip");

  document.body.classList.add(focusClass);
  document.documentElement.classList.add(focusClass);

  function expandExactRankingScores(scope) {
    if (!scope?.querySelectorAll) return;
    scope
      .querySelectorAll(
        ".gc-ranking-score .gc-num-compact, " +
          ".gc-ranking-mobile-score-inline .gc-num-compact, " +
          ".gc-ranking-my-strip .gc-num-compact"
      )
      .forEach((node) => {
        const full = String(node.getAttribute("title") || "").trim();
        if (full) node.textContent = full;
        node.removeAttribute("title");
        node.classList.remove("gc-num-compact");
        node.classList.add("gc-ranking-num-full");
      });
  }

  expandExactRankingScores(root);

  const observer = new MutationObserver(() => expandExactRankingScores(root));
  if (tableRoot) observer.observe(tableRoot, { childList: true, subtree: true });
  if (myStrip) observer.observe(myStrip, { childList: true, subtree: true });

  const cleanup = () => {
    observer.disconnect();
    document.body.classList.remove(focusClass);
    document.documentElement.classList.remove(focusClass);
  };

  if (window.GC && typeof window.GC.registerCleanup === "function") {
    window.GC.registerCleanup(cleanup);
  } else {
    window.addEventListener("pagehide", cleanup, { once: true });
  }
})();
