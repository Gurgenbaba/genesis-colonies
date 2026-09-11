(() => {
  "use strict";

  const focusClass = "gc-ranking-focus";
  const DEFAULT_PAGE_SIZE = 100;
  let activeRoot = null;
  let scoreObserver = null;
  let syncQueued = false;
  let paginationQueued = false;
  let rankingPage = 1;
  let rankingTabKey = "";

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

  function rankingPageSize() {
    const data = document.getElementById("ranking-initial-data");
    if (!data) return DEFAULT_PAGE_SIZE;
    try {
      const parsed = JSON.parse(data.textContent || "{}");
      const value = Number(parsed?.pagination?.page_size || DEFAULT_PAGE_SIZE);
      return Number.isFinite(value) && value > 0 ? Math.floor(value) : DEFAULT_PAGE_SIZE;
    } catch (_) {
      return DEFAULT_PAGE_SIZE;
    }
  }

  function activeRankingTabKey() {
    const tabs = document.getElementById("ranking-tabs");
    if (!tabs) return "ranking";
    const active = tabs.querySelector(
      '[aria-selected="true"], .is-active, .active, [data-active="true"]'
    );
    if (!active) return "ranking";
    return (
      active.getAttribute("data-tab") ||
      active.getAttribute("data-category") ||
      active.getAttribute("data-ranking-tab") ||
      String(active.textContent || "").trim() ||
      "ranking"
    );
  }

  function uniqueNodes(nodes) {
    return Array.from(new Set(nodes));
  }

  function rankingItemGroups(content) {
    const desktop = uniqueNodes(
      Array.from(content.querySelectorAll("table.gc-ranking-table tbody > tr"))
    );
    const mobile = uniqueNodes(
      Array.from(content.querySelectorAll(".gc-ranking-mobile .gc-ranking-mobile-card"))
    );
    return [desktop, mobile].filter((group) => group.length > 0);
  }

  function setRankingPage(root, page) {
    const content = root?.querySelector("#ranking-table-content");
    if (!content) return;
    const groups = rankingItemGroups(content);
    const total = groups.reduce((max, group) => Math.max(max, group.length), 0);
    const pageSize = rankingPageSize();
    const totalPages = Math.max(1, Math.ceil(total / pageSize));
    rankingPage = Math.max(1, Math.min(Number(page) || 1, totalPages));
    const start = (rankingPage - 1) * pageSize;
    const end = start + pageSize;

    groups.forEach((group) => {
      group.forEach((node, index) => {
        node.hidden = index < start || index >= end;
      });
    });

    let pager = content.querySelector(":scope > .gc-ranking-pager");
    if (totalPages <= 1) {
      if (pager) pager.remove();
      return;
    }

    if (!pager) {
      pager = document.createElement("nav");
      pager.className = "gc-ranking-pager";
      content.appendChild(pager);
    }

    const renderKey = [totalPages, rankingPage, pageSize].join(":");
    if (pager.dataset.renderKey === renderKey) return;
    pager.dataset.renderKey = renderKey;
    pager.replaceChildren();

    const addButton = (label, targetPage, disabled, current) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "gc-ranking-pager-btn";
      button.textContent = label;
      button.disabled = Boolean(disabled);
      if (current) button.setAttribute("aria-current", "page");
      button.addEventListener("click", () => {
        if (button.disabled) return;
        setRankingPage(root, targetPage);
        content.scrollIntoView({ block: "start", behavior: "smooth" });
      });
      pager.appendChild(button);
    };

    addButton("‹", rankingPage - 1, rankingPage <= 1, false);
    for (let pageNo = 1; pageNo <= totalPages; pageNo += 1) {
      addButton(String(pageNo), pageNo, pageNo === rankingPage, pageNo === rankingPage);
    }
    addButton("›", rankingPage + 1, rankingPage >= totalPages, false);
  }

  function applyRankingPagination(root) {
    paginationQueued = false;
    if (!root?.isConnected) return;
    const nextTabKey = activeRankingTabKey();
    if (rankingTabKey && rankingTabKey !== nextTabKey) rankingPage = 1;
    rankingTabKey = nextTabKey;
    setRankingPage(root, rankingPage);
  }

  function queueRankingPagination(root) {
    if (paginationQueued) return;
    paginationQueued = true;
    queueMicrotask(() => applyRankingPagination(root));
  }

  function deactivateRankingPage() {
    if (scoreObserver) {
      scoreObserver.disconnect();
      scoreObserver = null;
    }
    activeRoot = null;
    rankingPage = 1;
    rankingTabKey = "";
    paginationQueued = false;
    document.body.classList.remove(focusClass);
    document.documentElement.classList.remove(focusClass);
  }

  function activateRankingPage(root) {
    if (activeRoot === root) {
      expandExactRankingScores(root);
      queueRankingPagination(root);
      return;
    }

    deactivateRankingPage();
    activeRoot = root;
    document.body.classList.add(focusClass);
    document.documentElement.classList.add(focusClass);

    expandExactRankingScores(root);
    queueRankingPagination(root);
    scoreObserver = new MutationObserver((mutations) => {
      expandExactRankingScores(root);
      const rankingContentChanged = mutations.some((mutation) => {
        if (mutation.target?.closest?.(".gc-ranking-pager")) return false;
        const changed = [...mutation.addedNodes, ...mutation.removedNodes];
        return changed.some(
          (node) => !(node.nodeType === 1 && node.matches?.(".gc-ranking-pager"))
        );
      });
      if (rankingContentChanged) queueRankingPagination(root);
    });
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
