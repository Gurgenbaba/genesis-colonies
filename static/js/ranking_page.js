(() => {
  "use strict";

  const focusClass = "gc-ranking-focus";
  let activeRoot = null;
  let scoreObserver = null;
  let syncQueued = false;

  function expandExactRankingScores(scope) {
    if (!scope?.querySelectorAll) return;

    scope
      .querySelectorAll(
        ".gc-ranking-score [title], " +
          ".gc-ranking-mobile-score-inline [title], " +
          ".gc-ranking-my-strip [title]"
      )
      .forEach((node) => {
        const full = String(node.getAttribute("title") || "").trim();
        if (!full || !/\d/.test(full)) return;

        node.textContent = full;
        node.removeAttribute("title");
        node.classList.remove("gc-num-compact", "num-compact");
        node.classList.add("gc-ranking-num-full");
      });
  }

  function deactivateRankingPage() {
    if (scoreObserver) {
      scoreObserver.disconnect();
      scoreObserver = null;
    }
    activeRoot = null;
    document.body.classList.remove(focusClass);
    document.documentElement.classList.remove(focusClass);
  }

  function activateRankingPage(root) {
    if (activeRoot === root) {
      expandExactRankingScores(root);
      return;
    }

    deactivateRankingPage();
    activeRoot = root;
    document.body.classList.add(focusClass);
    document.documentElement.classList.add(focusClass);

    expandExactRankingScores(root);
    scoreObserver = new MutationObserver(() => expandExactRankingScores(root));
    scoreObserver.observe(root, { childList: true, subtree: true });
  }

  function syncRankingPage() {
    syncQueued = false;
    const root = document.getElementById("ranking-page");
    if (root) activateRankingPage(root);
    else if (activeRoot) deactivateRankingPage();
  }

  function queueSync() {
    if (syncQueued) return;
    syncQueued = true;
    queueMicrotask(syncRankingPage);
  }

  const mainContent = document.getElementById("main-content");
  const shellHost = mainContent?.parentElement || document.body;
  const shellObserver = new MutationObserver(queueSync);
  shellObserver.observe(shellHost, { childList: true, subtree: true });

  syncRankingPage();

  window.addEventListener(
    "pagehide",
    () => {
      deactivateRankingPage();
      shellObserver.disconnect();
    },
    { once: true }
  );
})();
