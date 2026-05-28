/* Genesis Colonies – player messages inbox (PJAX-safe) */
(() => {
  "use strict";

  const GC = (window.GC = window.GC || {});

  function msgDebug(...args) {
    try {
      const dev =
        GC.DEBUG === true ||
        window.localStorage?.getItem("gc_debug") === "1" ||
        /localhost|127\.0\.0\.1/.test(window.location.hostname || "");
      if (dev && typeof console !== "undefined" && console.debug) {
        console.debug(...args);
      }
    } catch (_) {}
  }

  function t(key, fallback) {
    try {
      const dict = window.GC_LOCALE || {};
      if (Object.prototype.hasOwnProperty.call(dict, key)) {
        const val = dict[key];
        if (val !== null && val !== undefined && String(val).length > 0) return String(val);
      }
    } catch (_) {}
    return fallback || key;
  }

  function esc(text) {
    return String(text ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function categoryLabel(cat) {
    return t(`messages.category.${cat}`, cat);
  }

  function formatTime(ts) {
    const n = Number(ts);
    if (!Number.isFinite(n) || n <= 0) return "–";
    try {
      return new Date(n * 1000).toLocaleString();
    } catch (_) {
      return String(n);
    }
  }

  async function messagesApi(url, options = {}) {
    const headers = {
      Accept: "application/json",
      "X-Requested-With": "XMLHttpRequest",
      ...(options.headers || {}),
    };
    const fetchOpts = {
      cache: "no-store",
      credentials: "same-origin",
      ...options,
      headers,
    };

    if (typeof GC.fetchJSON === "function") {
      try {
        const data = await GC.fetchJSON(url, fetchOpts);
        if (!data || typeof data !== "object") {
          return { ok: false, error: "error_load" };
        }
        return data;
      } catch (err) {
        if (err?.auth) return { ok: false, error: "not_logged_in" };
        return { ok: false, error: "error_load", status: err?.status || 0 };
      }
    }

    const res = await fetch(url, { ...fetchOpts, redirect: "manual" });
    const ct = (res.headers.get("content-type") || "").toLowerCase();
    if (res.type === "opaqueredirect" || res.status === 401 || res.status === 403) {
      return { ok: false, error: "not_logged_in", status: res.status };
    }
    if (!ct.includes("application/json")) {
      return { ok: false, error: "error_load", status: res.status };
    }
    try {
      const data = await res.json();
      if (!res.ok && data && typeof data === "object") {
        return { ...data, ok: false, status: res.status };
      }
      return data;
    } catch (_) {
      return { ok: false, error: "error_load", status: res.status };
    }
  }

  function syncUnreadFromResponse(data) {
    const n = data?.data?.unread_count;
    if (typeof n === "number") {
      updateLocalUnread(n);
      if (GC.messagesPageState) {
        GC.messagesPageState.unreadSyncedFromApi = true;
      }
      return true;
    }
    return false;
  }

  function updateLocalUnread(count) {
    const n = Math.max(0, Number(count) || 0);
    const el = document.getElementById("messages-unread-count");
    if (el) el.textContent = String(n);
    if (typeof GC.updateMessagesUnreadBadges === "function") {
      GC.updateMessagesUnreadBadges(n);
    }
    if (typeof GC.setMessagesUnreadPollBaseline === "function") {
      GC.setMessagesUnreadPollBaseline(n);
    }
  }

  function refreshBadgesFromServer() {
    if (typeof GC.refreshGameState === "function") {
      return GC.refreshGameState("messages_sync");
    }
    return Promise.resolve();
  }

  function getComposeDialog() {
    return document.getElementById("messages-compose-dialog");
  }

  function openCompose(recipient = "", subject = "") {
    const composeDialog = getComposeDialog();
    if (!composeDialog) return;
    const r = document.getElementById("messages-compose-recipient");
    const s = document.getElementById("messages-compose-subject");
    const b = document.getElementById("messages-compose-body");
    const composeStatus = document.getElementById("messages-compose-status");
    if (r) r.value = recipient;
    if (s) s.value = subject;
    if (b) b.value = "";
    if (composeStatus) composeStatus.textContent = "";
    if (typeof composeDialog.showModal === "function") {
      composeDialog.showModal();
    }
  }

  function closeCompose() {
    const dlg = getComposeDialog();
    if (dlg?.open) dlg.close();
  }

  function ensureMessagesState() {
    if (!document.getElementById("messages-page")) return null;
    if (!GC.messagesPageState) {
      initMessagesPage();
    }
    return GC.messagesPageState || null;
  }

  function resetMessagesPageState() {
    if (GC.messagesPageState?.listAbort) {
      try {
        GC.messagesPageState.listAbort.abort();
      } catch (_) {}
    }
    if (GC.messagesPageState) {
      GC.messagesPageState.loadGen += 1;
      GC.messagesPageState.unreadSyncedFromApi = false;
      GC.messagesPageState = null;
    }
    closeCompose();
  }

  function bindMessagesUiOnce() {
    if (GC._messagesUiBound) return;
    GC._messagesUiBound = true;

    const registerCleanup = GC.registerPageCleanup || GC.registerCleanup;
    if (typeof registerCleanup === "function") {
      registerCleanup(() => {
        msgDebug("[messages] cleanup (leave page)");
        resetMessagesPageState();
      }, { persistent: true });
    }

    const composeForm = document.getElementById("messages-compose-form");
    composeForm?.addEventListener("submit", async (e) => {
      e.preventDefault();
      e.stopPropagation();

      const state = GC.messagesPageState;
      const recipient = document.getElementById("messages-compose-recipient")?.value || "";
      const subject = document.getElementById("messages-compose-subject")?.value || "";
      const body = document.getElementById("messages-compose-body")?.value || "";
      const composeStatus = document.getElementById("messages-compose-status");
      if (composeStatus) composeStatus.textContent = "";

      const data = await messagesApi("/api/messages/send", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ recipient, subject, body }),
      });

      if (data?.ok) {
        if (composeStatus) composeStatus.textContent = t("messages.sent_success");
        closeCompose();
        // Sent mail is stored in the recipient inbox only — refresh badges, not sender list.
        await refreshBadgesFromServer();
        return;
      }

      const err = data?.error || "validation";
      if (composeStatus) {
        composeStatus.textContent = t(`messages.error_${err}`, t("messages.error_validation"));
      }
    });

    document.addEventListener("click", (e) => {
      const composeTo = e.target.closest("[data-messages-compose]");
      if (composeTo) {
        e.preventDefault();
        e.stopPropagation();
        openCompose(composeTo.dataset.recipientName || "");
        return;
      }

      const onMessagesPage = document.getElementById("messages-page");
      if (!onMessagesPage) return;

      const state = ensureMessagesState();
      if (!state) return;

      if (e.target.closest("#messages-compose-btn")) {
        e.preventDefault();
        e.stopPropagation();
        openCompose();
        return;
      }
      if (e.target.closest("#messages-compose-close")) {
        e.preventDefault();
        closeCompose();
        return;
      }

      if (e.target.closest("#messages-mark-all-read")) {
        e.preventDefault();
        e.stopPropagation();
        state.onMarkAllRead?.();
        return;
      }

      const tabBtn = e.target.closest("#messages-tabs .tab-btn[data-filter]");
      if (tabBtn) {
        e.preventDefault();
        const tabsEl = document.getElementById("messages-tabs");
        tabsEl?.querySelectorAll(".tab-btn").forEach((b) => {
          const active = b === tabBtn;
          b.classList.toggle("active", active);
          b.setAttribute("aria-selected", active ? "true" : "false");
        });
        state.filter = tabBtn.dataset.filter || "all";
        state.selectedId = null;
        state.setDetailVisible?.(false);
        state.loadList?.();
        return;
      }

      const item = e.target.closest(".gc-messages-item[data-id]");
      if (item) {
        e.preventDefault();
        const id = Number(item.dataset.id);
        if (Number.isFinite(id)) state.openMessage?.(id);
        return;
      }

      const actionBtn = e.target.closest("#messages-detail-actions button[data-action]");
      if (actionBtn && state.selectedId) {
        e.preventDefault();
        const msg = state.messages?.find((m) => m.id === state.selectedId);
        if (msg) state.handleAction?.(actionBtn.dataset.action, msg);
      }
    });
  }

  function readActiveFilterFromDom() {
    const activeTab = document.querySelector("#messages-tabs .tab-btn.active[data-filter]");
    return activeTab?.dataset.filter || "all";
  }

  function initMessagesPage(options) {
    bindMessagesUiOnce();

    const page = document.getElementById("messages-page");
    if (!page) {
      resetMessagesPageState();
      return;
    }

    resetMessagesPageState();

    msgDebug("[messages] init", { filter: readActiveFilterFromDom(), pjax: Boolean(options && options.pjax) });

    const getDetailEl = () => document.getElementById("messages-detail");
    const getDetailEmptyEl = () => document.getElementById("messages-detail-empty");
    const getDetailSubject = () => document.getElementById("messages-detail-subject");
    const getDetailMeta = () => document.getElementById("messages-detail-meta");
    const getDetailBody = () => document.getElementById("messages-detail-body");
    const getDetailActions = () => document.getElementById("messages-detail-actions");

    const state = {
      filter: readActiveFilterFromDom(),
      messages: [],
      selectedId: null,
      loadGen: 0,
      listAbort: null,
      unreadSyncedFromApi: false,
      listLoaded: false,
    };

    function setDetailVisible(show) {
      const detailEl = getDetailEl();
      const detailEmptyEl = getDetailEmptyEl();
      if (detailEl) detailEl.hidden = !show;
      if (detailEmptyEl) detailEmptyEl.hidden = show;
    }

    function showListMessage(html) {
      const listEl = document.getElementById("messages-list");
      if (listEl) listEl.innerHTML = html;
    }

    function renderList() {
      const listEl = document.getElementById("messages-list");
      if (!listEl) return;
      if (!state.listLoaded) {
        showListMessage(`<div class="gc-messages-empty">${esc(t("messages.loading"))}</div>`);
        return;
      }
      if (!state.messages.length) {
        showListMessage(`<div class="gc-messages-empty">${esc(t("messages.empty"))}</div>`);
        state.selectedId = null;
        setDetailVisible(false);
        return;
      }

      listEl.innerHTML = state.messages
        .map((m) => {
          const unread = !m.is_read;
          const active = state.selectedId === m.id ? " is-active" : "";
          const unreadCls = unread ? " is-unread" : "";
          return (
            `<button type="button" class="gc-messages-item${active}${unreadCls}" data-id="${m.id}">` +
            `<span class="gc-messages-item-subject">${esc(m.subject)}</span>` +
            `<span class="gc-messages-item-meta">${esc(categoryLabel(m.category))} · ${esc(formatTime(m.created_at))}</span>` +
            `</button>`
          );
        })
        .join("");
    }

    function renderDetail(msg) {
      if (!msg) {
        setDetailVisible(false);
        return;
      }
      setDetailVisible(true);
      const detailSubject = getDetailSubject();
      const detailMeta = getDetailMeta();
      const detailBody = getDetailBody();
      const detailActions = getDetailActions();
      if (detailSubject) detailSubject.textContent = msg.subject || "";
      const sender = msg.sender_name || categoryLabel(msg.category);
      if (detailMeta) {
        detailMeta.textContent = `${sender} · ${categoryLabel(msg.category)} · ${formatTime(msg.created_at)}`;
      }
      if (detailBody) detailBody.textContent = msg.body || "";

      if (!detailActions) return;
      detailActions.innerHTML = "";

      const mkBtn = (label, action, variant = "outline") => {
        const b = document.createElement("button");
        b.type = "button";
        const cls =
          variant === "primary"
            ? "gc-btn gc-btn-primary gc-btn-sm"
            : variant === "danger"
              ? "gc-btn gc-btn-danger gc-btn-sm"
              : "gc-btn gc-btn-outline gc-btn-sm";
        b.className = cls;
        b.dataset.action = action;
        b.textContent = label;
        return b;
      };

      if (!msg.is_read) detailActions.appendChild(mkBtn(t("messages.read"), "read", "outline"));
      if (msg.reply_to_player_id || msg.sender_player_id) {
        detailActions.appendChild(mkBtn(t("messages.reply"), "reply", "primary"));
      }
      if (!msg.is_archived) detailActions.appendChild(mkBtn(t("messages.archive"), "archive", "outline"));
      detailActions.appendChild(mkBtn(t("messages.delete"), "delete", "danger"));
    }

    function isActiveState(gen) {
      return (
        state === GC.messagesPageState &&
        gen === state.loadGen &&
        document.getElementById("messages-page")
      );
    }

    async function loadList(retryNotReady = true) {
      const gen = ++state.loadGen;
      const ctrl = new AbortController();
      state.listAbort = ctrl;

      showListMessage(`<div class="gc-messages-empty">${esc(t("messages.loading"))}</div>`);

      try {
        const params = new URLSearchParams({ limit: "50" });
        if (state.filter && state.filter !== "all") params.set("category", state.filter);
        if (state.filter === "archive") params.set("include_archived", "1");

        const data = await messagesApi(`/api/messages?${params.toString()}`, {
          signal: ctrl.signal,
        });

        if (ctrl.signal.aborted || !isActiveState(gen)) return;

        if (!data || !data.ok) {
          const err = data?.error || "error_load";
          if ((err === "messages_not_ready" || data?.status === 503) && retryNotReady && isActiveState(gen)) {
            await new Promise((r) => setTimeout(r, 400));
            if (isActiveState(gen)) return loadList(false);
          }
          const errLabel = esc(t(`messages.error_${err}`, t("messages.error_load")));
          showListMessage(
            `<div class="gc-messages-empty">` +
              `<p>${errLabel}</p>` +
              `<button type="button" class="gc-btn gc-btn-outline gc-btn-sm" data-messages-retry>` +
              `${esc(t("messages.retry", "Erneut laden"))}</button>` +
              `</div>`
          );
          listEl?.querySelector("[data-messages-retry]")?.addEventListener("click", () => {
            loadList();
          });
          return;
        }

        state.messages = data.data?.messages || [];
        state.listLoaded = true;
        syncUnreadFromResponse(data);
        renderList();
        msgDebug("[messages] inbox loaded", {
          player_id: data.data?.player_id,
          count: state.messages.length,
          unread: data.data?.unread_count,
          filter: state.filter,
        });

        if (state.selectedId) {
          const current = state.messages.find((m) => m.id === state.selectedId);
          if (current) renderDetail(current);
          else {
            state.selectedId = null;
            setDetailVisible(false);
          }
        }
      } catch (err) {
        if (err?.name === "AbortError") return;
        if (!isActiveState(gen)) return;
        showListMessage(`<div class="gc-messages-empty">${esc(t("messages.error_load"))}</div>`);
      } finally {
        if (state.listAbort === ctrl) state.listAbort = null;
      }
    }

    function showDetailError(key) {
      setDetailVisible(true);
      const detailSubject = getDetailSubject();
      const detailMeta = getDetailMeta();
      const detailBody = getDetailBody();
      const detailActions = getDetailActions();
      if (detailSubject) detailSubject.textContent = t("messages.error_load", "Could not load message.");
      if (detailMeta) detailMeta.textContent = "";
      if (detailBody) {
        detailBody.textContent = t(`messages.error_${key}`, t("messages.error_load"));
      }
      if (detailActions) detailActions.innerHTML = "";
    }

    async function openMessage(id) {
      const data = await messagesApi(`/api/messages/${id}`);
      if (state !== GC.messagesPageState || !document.getElementById("messages-page")) return;
      if (!data || !data.ok) {
        showDetailError(data?.error || "load");
        return;
      }
      const msg = data.data?.message;
      if (!msg) {
        showDetailError("load");
        return;
      }
      state.selectedId = id;
      const idx = state.messages.findIndex((m) => m.id === id);
      if (idx >= 0) state.messages[idx] = msg;
      renderList();
      renderDetail(msg);
      if (!syncUnreadFromResponse(data)) await refreshBadgesFromServer();
    }

    async function postAction(url) {
      const data = await messagesApi(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({}),
      });
      if (!syncUnreadFromResponse(data)) await refreshBadgesFromServer();
      return data;
    }

    async function handleAction(action, msg) {
      if (!msg) return;
      if (action === "read") await postAction(`/api/messages/${msg.id}/read`);
      else if (action === "archive") await postAction(`/api/messages/${msg.id}/archive`);
      else if (action === "delete") {
        if (!window.confirm(t("messages.delete_confirm"))) return;
        await postAction(`/api/messages/${msg.id}/delete`);
        state.selectedId = null;
        setDetailVisible(false);
      } else if (action === "reply") {
        openCompose(msg.reply_to_name || msg.sender_name || "", msg.subject ? `Re: ${msg.subject}` : "");
        return;
      }
      await loadList();
      if (state.selectedId && action !== "delete") await openMessage(state.selectedId);
    }

    state.onMarkAllRead = async () => {
      const payload = {};
      if (state.filter && !["all", "archive"].includes(state.filter)) {
        payload.category = state.filter;
      }
      const data = await messagesApi("/api/messages/read-all", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (data?.ok) {
        syncUnreadFromResponse(data);
        await loadList();
      } else {
        const err = data?.error || "error_load";
        showListMessage(
          `<div class="gc-messages-empty">${esc(t(`messages.error_${err}`, t("messages.error_load")))}</div>`
        );
      }
    };

    state.loadList = loadList;
    state.openMessage = openMessage;
    state.handleAction = handleAction;
    state.setDetailVisible = setDetailVisible;

    GC.messagesPageState = state;
    loadList();
    const retryLater = typeof GC.setSafeTimeout === "function" ? GC.setSafeTimeout : setTimeout;
    retryLater(() => {
      if (state !== GC.messagesPageState || !document.getElementById("messages-page")) return;
      if (state.listLoaded || state.messages.length > 0 || state.unreadSyncedFromApi) return;
      const listNode = document.getElementById("messages-list");
      const loading = (listNode?.textContent || "").includes(t("messages.loading"));
      if (loading) loadList(false);
    }, 2500);
  }

  GC.modules = GC.modules || {};
  GC.modules.messages = initMessagesPage;
  GC.initMessagesPage = initMessagesPage;
  GC.openMessagesCompose = openCompose;
  GC.ensureMessagesState = ensureMessagesState;
  bindMessagesUiOnce();

  function bootMessagesIfPresent() {
    if (document.getElementById("messages-page")) {
      initMessagesPage();
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", bootMessagesIfPresent);
  } else {
    bootMessagesIfPresent();
  }
})();
