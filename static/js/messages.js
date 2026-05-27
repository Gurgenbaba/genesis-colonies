/* Genesis Colonies – player messages inbox (PJAX-safe) */
(() => {
  "use strict";

  const GC = (window.GC = window.GC || {});

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
    const res = await fetch(url, {
      credentials: "same-origin",
      cache: "no-store",
      headers: {
        Accept: "application/json",
        ...(options.headers || {}),
      },
      ...options,
    });
    const ct = (res.headers.get("content-type") || "").toLowerCase();
    if (!ct.includes("application/json")) {
      return { ok: false, error: "error_load" };
    }
    try {
      return await res.json();
    } catch (_) {
      return { ok: false, error: "error_load" };
    }
  }

  function syncUnreadFromResponse(data) {
    const n = data?.data?.unread_count;
    if (typeof n === "number") {
      updateLocalUnread(n);
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

  function bindMessagesUiOnce() {
    if (GC._messagesUiBound) return;
    GC._messagesUiBound = true;

    if (typeof GC.registerPageCleanup === "function") {
      GC.registerPageCleanup(() => {
        if (GC.messagesPageState) {
          GC.messagesPageState.loadGen += 1;
          GC.messagesPageState = null;
        }
        closeCompose();
      });
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
        if (state && typeof state.loadList === "function") {
          await state.loadList();
        }
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

      if (!document.getElementById("messages-page")) return;

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

      let state = GC.messagesPageState;
      const itemEarly = e.target.closest(".gc-messages-item[data-id]");
      if (itemEarly && !state) {
        e.preventDefault();
        initMessagesPage();
        state = GC.messagesPageState;
      }
      if (!state) return;
      if (e.target.closest("#messages-mark-all-read")) {
        e.preventDefault();
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

  function initMessagesPage() {
    bindMessagesUiOnce();

    const page = document.getElementById("messages-page");
    if (!page) {
      GC.messagesPageState = null;
      return;
    }

    closeCompose();

    const listEl = document.getElementById("messages-list");
    const detailEl = document.getElementById("messages-detail");
    const detailEmptyEl = document.getElementById("messages-detail-empty");
    const detailSubject = document.getElementById("messages-detail-subject");
    const detailMeta = document.getElementById("messages-detail-meta");
    const detailBody = document.getElementById("messages-detail-body");
    const detailActions = document.getElementById("messages-detail-actions");

    const state = {
      filter: "all",
      messages: [],
      selectedId: null,
      loadGen: 0,
    };

    function setDetailVisible(show) {
      if (detailEl) detailEl.hidden = !show;
      if (detailEmptyEl) detailEmptyEl.hidden = show;
    }

    function showListMessage(html) {
      if (listEl) listEl.innerHTML = html;
    }

    function renderList() {
      if (!listEl) return;
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

    async function loadList() {
      const gen = ++state.loadGen;
      showListMessage(`<div class="gc-messages-empty">${esc(t("messages.loading"))}</div>`);

      try {
        const params = new URLSearchParams({ limit: "50" });
        if (state.filter && state.filter !== "all") params.set("category", state.filter);
        if (state.filter === "archive") params.set("include_archived", "1");

        const data = await messagesApi(`/api/messages?${params.toString()}`);
        if (gen !== state.loadGen || !document.getElementById("messages-page")) return;

        if (!data || !data.ok) {
          const err = data?.error || "error";
          showListMessage(
            `<div class="gc-messages-empty">${esc(t(`messages.error_${err}`, t("messages.error_load")))}</div>`
          );
          return;
        }

        state.messages = data.data?.messages || [];
        syncUnreadFromResponse(data);
        renderList();

        if (state.selectedId) {
          const current = state.messages.find((m) => m.id === state.selectedId);
          if (current) renderDetail(current);
          else {
            state.selectedId = null;
            setDetailVisible(false);
          }
        }
      } catch (_) {
        if (gen !== state.loadGen) return;
        showListMessage(`<div class="gc-messages-empty">${esc(t("messages.error_load"))}</div>`);
      }
    }

    function showDetailError(key) {
      setDetailVisible(true);
      if (detailSubject) detailSubject.textContent = t("messages.error_load", "Could not load message.");
      if (detailMeta) detailMeta.textContent = "";
      if (detailBody) {
        detailBody.textContent = t(`messages.error_${key}`, t("messages.error_load"));
      }
      if (detailActions) detailActions.innerHTML = "";
    }

    async function openMessage(id) {
      const data = await messagesApi(`/api/messages/${id}`);
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
        body: "{}",
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
      syncUnreadFromResponse(data);
      await loadList();
      await refreshBadgesFromServer();
    };

    state.loadList = loadList;
    state.openMessage = openMessage;
    state.handleAction = handleAction;
    state.setDetailVisible = setDetailVisible;

    GC.messagesPageState = state;
    loadList();
  }

  GC.modules = GC.modules || {};
  GC.modules.messages = initMessagesPage;
  GC.initMessagesPage = initMessagesPage;
  GC.openMessagesCompose = openCompose;
  bindMessagesUiOnce();
})();
