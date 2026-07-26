/* ============================================================================
   Genesis TChat – PJAX-safe singleton, docked inside .gc-layout
   ============================================================================ */
(() => {
  "use strict";

  const GC = window.GC || {};
  window.GC = GC;

  const MIN_W = 280;
  const MIN_H = 280;
  const MAX_W = 720;
  const DOCK_PAD = 12;

  const CHAT_EMOJIS = [
    "😀", "😂", "😊", "😎", "🤔", "😅", "😢", "😡",
    "👍", "👎", "👏", "🙏", "💪", "✌️", "🤝", "👋",
    "❤️", "🔥", "⭐", "✨", "💯", "🎉", "🚀", "⚡",
    "🌍", "🏗️", "⚔️", "🛡️", "💎", "📦", "🔧", "📡",
  ];

  function t(key, fallback) {
    try {
      const dict = window.GC_LOCALE || {};
      if (Object.prototype.hasOwnProperty.call(dict, key)) {
        const v = dict[key];
        if (v !== null && v !== undefined && String(v).length) return String(v);
      }
    } catch (_) {}
    return fallback || key;
  }

  function chatDebug(...args) {
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

  const CHAT = {
    root: null,
    panel: null,
    fab: null,
    roomList: null,
    messagesEl: null,
    input: null,
    errorEl: null,
    newMsgsBtn: null,
    autocompleteEl: null,
    activeTitle: null,
    roomHint: null,
    roomMembers: null,
    fabBadge: null,
    maximizeBtn: null,
    emojiToggle: null,
    emojiPicker: null,
    roomCreateBtn: null,
    roomInviteBtn: null,
    roomRemoveBtn: null,
    roomLeaveBtn: null,
    roomDeleteBtn: null,
    bootstrap: null,
    uiState: null,
    activeRoomId: null,
    lastMsgIdByRoom: {},
    unread: {},
    mentionUnread: {},
    polling: {
      timer: null,
      abort: null,
      started: false,
      interval: 8000,
      intervalHidden: 12000,
      // GC-PERF-CHAT-IDLE-001: slow message poll while panel closed (badge via bootstrap).
      intervalClosed: 45000,
      bootstrapIntervalMs: 60000,
      lastBootstrapAt: 0,
      bootstrapInFlight: null,
    },
    stateSaveTimer: null,
    uiBound: false,
    rootEventsBound: false,
    dragBound: false,
    emojiDismissBound: false,
    whisperBound: false,
    lifecycleBound: false,
    stickToBottom: true,
    pendingNew: 0,
    isMobile: false,
    isMaximized: false,
    useCustomPosition: false,
    viewerName: "",
    viewerId: 0,
  };

  const LOCAL_STATE_KEY = "gc_chat_ui_state_v1";
  const STATE_VERSION = 1;

  function loadLocalUiState() {
    try {
      const raw = window.localStorage?.getItem(LOCAL_STATE_KEY);
      if (!raw) return {};
      const data = JSON.parse(raw);
      if (!data || typeof data !== "object") return {};
      return data;
    } catch (_) {
      return {};
    }
  }

  function saveLocalUiState(state) {
    try {
      if (!state || typeof state !== "object") return;
      window.localStorage?.setItem(LOCAL_STATE_KEY, JSON.stringify(state));
    } catch (_) {}
  }

  function sanitizeUiState(state) {
    const src = state && typeof state === "object" ? state : {};
    const vp = getViewportBounds();
    const width = Math.max(MIN_W, Math.min(MAX_W, Number(src.width) || 380));
    const height = Math.max(MIN_H, Math.min(vp.height, Number(src.height) || 480));
    const out = {
      version: STATE_VERSION,
      saved_at: Number(src.saved_at) || 0,
      is_open: !!src.is_open,
      is_minimized: src.is_minimized !== false,
      active_room_id: src.active_room_id ? Number(src.active_room_id) : null,
      width,
      height,
      pos_x: Number(src.pos_x) || 0,
      pos_y: Number(src.pos_y) || 0,
    };

    if (out.pos_x > 0 || out.pos_y > 0) {
      const maxX = Math.max(vp.left, vp.left + vp.width - width);
      const maxY = Math.max(vp.top, vp.top + vp.height - height);
      out.pos_x = Math.max(vp.left, Math.min(out.pos_x, maxX));
      out.pos_y = Math.max(vp.top, Math.min(out.pos_y, maxY));
    }
    return out;
  }

  function mergeUiState(serverState, localState) {
    const s = sanitizeUiState(serverState || {});
    const l = sanitizeUiState(localState || {});
    const sTs = Number(s.saved_at || 0);
    const lTs = Number(l.saved_at || 0);
    const picked = lTs > sTs ? l : s;
    return sanitizeUiState({ ...s, ...picked });
  }

  function qs(sel, root) {
    return (root || CHAT.root || document).querySelector(sel);
  }

  function getViewportBounds() {
    const pad = DOCK_PAD;
    return {
      left: pad,
      top: 72,
      width: window.innerWidth - pad * 2,
      height: window.innerHeight - 100,
    };
  }

  function apiFetch(url, options = {}) {
    return fetch(url, {
      credentials: "same-origin",
      headers: {
        "Content-Type": "application/json",
        "X-Requested-With": "XMLHttpRequest",
        ...(options.headers || {}),
      },
      ...options,
    }).then(async (res) => {
      let data = {};
      try {
        data = await res.json();
      } catch (_) {}
      return { res, data };
    }).catch((err) => {
      if (err?.name === "AbortError") throw err;
      throw err;
    });
  }

  function showError(key) {
    if (!CHAT.errorEl) return;
    const i18nKey = {
      no_permission: "chat_error_no_permission",
      muted: "chat_error_muted",
      rate_limited: "chat_error_rate_limited",
      player_not_found: "chat_error_player_not_found",
      empty_message: "chat_error_empty_message",
      message_too_long: "chat_error_message_too_long",
      cannot_whisper_self: "chat_error_cannot_whisper_self",
      owner_cannot_leave_room: "chat_error_owner_cannot_leave_room",
    }[key] || `chat_error_${key}`;
    const msg = t(i18nKey, key);
    CHAT.errorEl.textContent = msg === `chat_error_${key}` ? key : msg;
    CHAT.errorEl.hidden = false;
    clearTimeout(CHAT._errTimer);
    CHAT._errTimer = setTimeout(() => {
      if (CHAT.errorEl) CHAT.errorEl.hidden = true;
    }, 4000);
  }

  function clearError() {
    if (CHAT.errorEl) {
      CHAT.errorEl.hidden = true;
      CHAT.errorEl.textContent = "";
    }
  }

  function roomLabel(room) {
    if (!room) return "—";
    if (room.disabled) return t("chat_alliance", "Allianz");
    const type = room.room_type;
    if (type === "global") return t("chat_global", "Global");
    if (type === "system") return t("chat_system", "System");
    if (type === "alliance") return room.title || t("chat_alliance", "Allianz");
    if (type === "dm") return room.dm_partner_name || t("chat_dm", "Privat");
    if (type === "admin") return t("chat_admin", "Admin");
    if (type === "custom") return room.title || t("chat_custom_room", "Raum");
    return room.title || room.room_key;
  }

  function isChatPanelVisible() {
    return !!CHAT.root?.classList.contains("is-open");
  }

  function isActivelyViewingRoom(roomId) {
    return isChatPanelVisible() && Number(roomId) === Number(CHAT.activeRoomId);
  }

  function isOwnChatMessage(msg) {
    const sid = Number(msg?.sender_id || 0);
    return CHAT.viewerId > 0 && sid > 0 && sid === CHAT.viewerId;
  }

  function filterFreshMessages(roomId, messages) {
    const prevLast = Number(CHAT.lastMsgIdByRoom[roomId] || 0);
    return (messages || []).filter(
      (m) => Number(m.id) > prevLast && !isOwnChatMessage(m)
    );
  }

  function bumpLastMsgId(roomId, messages) {
    let maxId = Number(CHAT.lastMsgIdByRoom[roomId] || 0);
    for (const m of messages || []) {
      const mid = Number(m.id);
      if (mid > maxId) maxId = mid;
    }
    if (maxId > 0) CHAT.lastMsgIdByRoom[roomId] = maxId;
    return maxId;
  }

  function applyIncomingPollMessages(roomId, messages) {
    if (!messages?.length) return;

    const prevLast = Number(CHAT.lastMsgIdByRoom[roomId] || 0);
    bumpLastMsgId(roomId, messages);
    const fresh = (messages || []).filter(
      (m) => Number(m.id) > prevLast && !isOwnChatMessage(m)
    );
    if (!fresh.length) return;

    const rid = String(roomId);

    if (isActivelyViewingRoom(roomId)) {
      renderMessages(fresh, true);
      return;
    }

    const beforeUnread = totalUnread();
    CHAT.unread[rid] = (CHAT.unread[rid] || 0) + fresh.length;
    for (const m of fresh) {
      if (detectMention(m.message)) CHAT.mentionUnread[rid] = true;
    }
    updateFabBadge();
    renderRoomList();
    notifyChatUnreadIfIncreased(beforeUnread);
  }

  function getActiveRoom() {
    return (CHAT.bootstrap?.rooms || []).find((r) => Number(r.id) === Number(CHAT.activeRoomId)) || null;
  }

  function totalUnread() {
    return Object.values(CHAT.unread).reduce((a, b) => a + (Number(b) || 0), 0);
  }

  function pruneRoomState() {
    const valid = new Set((CHAT.bootstrap?.rooms || []).filter((r) => r?.id).map((r) => String(r.id)));
    for (const key of Object.keys(CHAT.unread || {})) {
      if (!valid.has(String(key))) delete CHAT.unread[key];
    }
    for (const key of Object.keys(CHAT.mentionUnread || {})) {
      if (!valid.has(String(key))) delete CHAT.mentionUnread[key];
    }
    for (const key of Object.keys(CHAT.lastMsgIdByRoom || {})) {
      if (!valid.has(String(key))) delete CHAT.lastMsgIdByRoom[key];
    }
  }

  function updateFabBadge() {
    const n = totalUnread();
    if (CHAT.fabBadge) {
      if (n > 0) {
        CHAT.fabBadge.textContent = n > 99 ? "99+" : String(n);
        CHAT.fabBadge.hidden = false;
        CHAT.fabBadge.removeAttribute("hidden");
      } else {
        CHAT.fabBadge.hidden = true;
        CHAT.fabBadge.setAttribute("hidden", "");
        CHAT.fabBadge.textContent = "";
      }
    }
    document.querySelectorAll("[data-chat-launcher-badge]").forEach((badge) => {
      const btn = badge.closest("[data-special-open-window='chat'], .gc-special-bar-btn");
      if (n > 0) {
        badge.textContent = n > 99 ? "99+" : String(n);
        badge.hidden = false;
        badge.removeAttribute("hidden");
        badge.setAttribute("aria-hidden", "false");
        if (btn) btn.classList.add("has-chat-unread");
      } else {
        badge.hidden = true;
        badge.setAttribute("hidden", "");
        badge.textContent = "";
        badge.setAttribute("aria-hidden", "true");
        if (btn) btn.classList.remove("has-chat-unread");
      }
    });
  }

  function updateNewMsgsBtn() {
    if (!CHAT.newMsgsBtn) return;
    if (CHAT.pendingNew > 0) {
      CHAT.newMsgsBtn.hidden = false;
      CHAT.newMsgsBtn.textContent = t("chat_new_messages_count", "Neue Nachrichten (%(count)s)").replace(
        "%(count)s",
        String(CHAT.pendingNew)
      ).replace("{count}", String(CHAT.pendingNew));
    } else {
      CHAT.newMsgsBtn.hidden = true;
    }
  }

  function dockPanel() {
    if (!CHAT.panel || CHAT.isMobile || CHAT.isMaximized) return;
    CHAT.useCustomPosition = false;
    CHAT.panel.classList.remove("is-custom-pos");
    CHAT.panel.style.left = "";
    CHAT.panel.style.top = "";
    CHAT.panel.style.right = "";
    CHAT.panel.style.bottom = "";
  }

  function clampPanelToViewport() {
    if (!CHAT.panel || CHAT.isMaximized) return;
    const vp = getViewportBounds();
    const pw = CHAT.panel.offsetWidth;
    const ph = CHAT.panel.offsetHeight;
    const w = Math.max(MIN_W, Math.min(MAX_W, Math.min(pw, vp.width)));
    const h = Math.max(MIN_H, Math.min(ph, vp.height));
    CHAT.panel.style.width = `${w}px`;
    CHAT.panel.style.height = `${h}px`;

    if (!CHAT.useCustomPosition) {
      dockPanel();
      return;
    }

    const rect = CHAT.panel.getBoundingClientRect();
    let left = rect.left;
    let top = rect.top;
    left = Math.max(vp.left, Math.min(left, vp.left + vp.width - w));
    top = Math.max(vp.top, Math.min(top, vp.top + vp.height - h));

    CHAT.panel.classList.add("is-custom-pos");
    CHAT.panel.style.right = "auto";
    CHAT.panel.style.bottom = "auto";
    CHAT.panel.style.left = `${Math.round(left)}px`;
    CHAT.panel.style.top = `${Math.round(top)}px`;
  }

  function applyPanelGeometry(state) {
    if (!CHAT.panel) return;
    const src = sanitizeUiState(state || CHAT.uiState || {});
    const w = Math.max(MIN_W, Math.min(MAX_W, Number(src.width) || 380));
    const h = Math.max(MIN_H, Number(src.height) || 480);
    CHAT.panel.style.width = `${w}px`;
    CHAT.panel.style.height = `${h}px`;

    const px = Number(src.pos_x) || 0;
    const py = Number(src.pos_y) || 0;
    if (!CHAT.isMobile && px > 0 && py > 0) {
      CHAT.useCustomPosition = true;
      CHAT.panel.classList.add("is-custom-pos");
      CHAT.panel.style.right = "auto";
      CHAT.panel.style.bottom = "auto";
      CHAT.panel.style.left = `${px}px`;
      CHAT.panel.style.top = `${py}px`;
    } else if (!CHAT.isMaximized) {
      dockPanel();
    }
    clampPanelToViewport();
    CHAT.uiState = sanitizeUiState({ ...(CHAT.uiState || {}), ...src, width: w, height: h, pos_x: px, pos_y: py });
  }

  function readPanelStateForSave() {
    if (!CHAT.panel) {
      return { pos_x: 0, pos_y: 0, width: 380, height: 480 };
    }
    if (CHAT.isMobile) {
      return {
        pos_x: Number(CHAT.uiState?.pos_x) || 0,
        pos_y: Number(CHAT.uiState?.pos_y) || 0,
        width: Number(CHAT.uiState?.width) || 380,
        height: Number(CHAT.uiState?.height) || 480,
      };
    }
    const rect = CHAT.panel.getBoundingClientRect();
    const width = CHAT.panel.offsetWidth || Math.round(rect.width) || Number(CHAT.uiState?.width) || 380;
    const height = CHAT.panel.offsetHeight || Math.round(rect.height) || Number(CHAT.uiState?.height) || 480;
    const body = {
      width,
      height,
      pos_x: 0,
      pos_y: 0,
    };
    if (CHAT.useCustomPosition) {
      body.pos_x = Math.round(rect.left || Number(CHAT.uiState?.pos_x) || 0);
      body.pos_y = Math.round(rect.top || Number(CHAT.uiState?.pos_y) || 0);
    }
    return body;
  }

  async function saveState(patch) {
    const geom = readPanelStateForSave();
    const now = Math.floor(Date.now() / 1000);
    const body = {
      ...(CHAT.uiState || {}),
      ...geom,
      version: STATE_VERSION,
      saved_at: now,
      is_open: CHAT.root?.classList.contains("is-open"),
      is_minimized: !CHAT.root?.classList.contains("is-open"),
      active_room_id: CHAT.activeRoomId,
      ...patch,
    };
    CHAT.uiState = sanitizeUiState({ ...(CHAT.uiState || {}), ...body });
    saveLocalUiState(CHAT.uiState);
    try {
      await apiFetch("/api/chat/state", {
        method: "POST",
        body: JSON.stringify(CHAT.uiState),
      });
    } catch (_) {}
  }

  function persistState(patch, immediate) {
    if (immediate) {
      clearTimeout(CHAT.stateSaveTimer);
      return saveState(patch, true);
    }
    debouncedSaveState(patch);
  }

  function debouncedSaveState(patch) {
    clearTimeout(CHAT.stateSaveTimer);
    CHAT.stateSaveTimer = setTimeout(() => saveState(patch), 400);
  }

  function setMinimized() {
    if (!CHAT.root) return;
    GC._chatWantsOpen = false;
    const geom = readPanelStateForSave();
    hideEmojiPicker();
    CHAT.root.classList.remove("is-open");
    CHAT.root.setAttribute("aria-hidden", "true");
    if (CHAT.fab) CHAT.fab.style.removeProperty("display");
    persistState({ ...geom, is_open: false, is_minimized: true }, true);
  }

  function setOpen(open) {
    if (!CHAT.root) return;
    CHAT.root.hidden = false;
    CHAT.root.removeAttribute("hidden");
    CHAT.root.setAttribute("aria-hidden", "false");

    if (!open) {
      setMinimized();
      schedulePoll();
      return;
    }

    GC._chatWantsOpen = true;
    CHAT.root.classList.add("is-open");
    if (CHAT.fab) CHAT.fab.style.removeProperty("display");
    applyPanelGeometry(CHAT.uiState);
    updateActiveRoomHeader();

    if (CHAT.input) {
      try {
        CHAT.input.focus({ preventScroll: true });
      } catch (_) {}
    }
    scrollToBottom(true);
    markRead();
    persistState({ is_open: true, is_minimized: false }, true);
    schedulePoll();
  }

  function toggleMaximize() {
    if (!CHAT.root || !CHAT.panel) return;
    CHAT.isMaximized = !CHAT.isMaximized;
    CHAT.root.classList.toggle("is-maximized", CHAT.isMaximized);

    const btn = CHAT.maximizeBtn || qs("[data-chat-maximize]");
    if (btn) {
      btn.classList.toggle("is-active", CHAT.isMaximized);
      btn.textContent = CHAT.isMaximized ? "❐" : "□";
      btn.setAttribute(
        "aria-label",
        CHAT.isMaximized ? t("chat_restore", "Wiederherstellen") : t("chat_maximize", "Maximieren")
      );
    }

    if (!CHAT.isMaximized) {
      if (CHAT.useCustomPosition) clampPanelToViewport();
      else dockPanel();
    }
    debouncedSaveState({});
  }

  function formatTime(ts) {
    if (typeof GC.formatLocaleDateTime === "function") return GC.formatLocaleDateTime(ts);
    const n = Number(ts);
    if (!Number.isFinite(n) || n <= 0) return "–";
    try {
      const ms = n < 1e12 ? n * 1000 : n;
      return new Intl.DateTimeFormat("de-DE", { dateStyle: "short", timeStyle: "short" }).format(new Date(ms));
    } catch (_) {
      return "–";
    }
  }

  function isNearBottom() {
    if (!CHAT.messagesEl) return true;
    const el = CHAT.messagesEl;
    return el.scrollHeight - el.scrollTop - el.clientHeight < 64;
  }

  function scrollToBottom(force) {
    if (!CHAT.messagesEl) return;
    if (!force && !CHAT.stickToBottom) return;
    CHAT.messagesEl.scrollTop = CHAT.messagesEl.scrollHeight;
    CHAT.pendingNew = 0;
    updateNewMsgsBtn();
    markRead();
  }

  function detectMention(text) {
    if (!CHAT.viewerName || !text) return false;
    const re = new RegExp(`@${CHAT.viewerName.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}\\b`, "i");
    return re.test(text);
  }

  function renderMessages(messages, append) {
    if (!CHAT.messagesEl) return;
    if (!append) CHAT.messagesEl.innerHTML = "";

    const frag = document.createDocumentFragment();
    for (const m of messages) {
      const row = document.createElement("article");
      row.className = "gc-chat-msg";
      row.dataset.messageId = String(m.id);
      if (m.message_type === "system") row.classList.add("is-system");
      if (m.message_type === "action") row.classList.add("is-action");
      if (m.message_type === "whisper") row.classList.add("is-whisper");
      if (m.is_deleted) row.classList.add("is-deleted");

      const meta = document.createElement("div");
      meta.className = "gc-chat-msg-meta";

      if (m.sender_id && !m.is_deleted) {
        const sender = document.createElement("button");
        sender.type = "button";
        sender.className = "gc-chat-msg-sender gc-player-name";
        sender.textContent = m.sender_name || "?";
        sender.dataset.playerId = String(m.sender_id);
        sender.dataset.playerName = m.sender_name || "";
        sender.dataset.nameStyle = m.sender_name_style || "none";
        sender.setAttribute("data-name-style", m.sender_name_style || "none");
        sender.title = t("chat_whisper_to", "Flüstern");
        meta.appendChild(sender);
      } else {
        const sys = document.createElement("span");
        sys.textContent = m.sender_name || t("chat_system", "System");
        meta.appendChild(sys);
      }

      if (m.sender_alliance_tag) {
        const tag = document.createElement("span");
        tag.className = "gc-chat-msg-tag";
        tag.textContent = `[${m.sender_alliance_tag}]`;
        meta.appendChild(tag);
      }

      const time = document.createElement("span");
      time.className = "gc-chat-msg-time";
      time.textContent = formatTime(m.created_at);
      meta.appendChild(time);

      const body = document.createElement("div");
      body.className = "gc-chat-msg-body";
      if (m.is_deleted) {
        body.textContent = t("chat_message_deleted", "Nachricht entfernt");
      } else if (m.body_rendered) {
        body.innerHTML = m.body_rendered;
      } else {
        body.textContent = m.message || "";
      }

      row.appendChild(meta);
      row.appendChild(body);
      frag.appendChild(row);

      const mid = Number(m.id);
      if (mid > (CHAT.lastMsgIdByRoom[CHAT.activeRoomId] || 0)) {
        CHAT.lastMsgIdByRoom[CHAT.activeRoomId] = mid;
      }

      if (!append && detectMention(m.message)) {
        CHAT.mentionUnread[String(CHAT.activeRoomId)] = true;
      }
    }

    CHAT.messagesEl.appendChild(frag);

    if (append && !isNearBottom()) {
      CHAT.pendingNew += messages.length;
      for (const m of messages) {
        if (detectMention(m.message)) CHAT.mentionUnread[String(CHAT.activeRoomId)] = true;
      }
      updateNewMsgsBtn();
      renderRoomList();
    } else {
      scrollToBottom(append);
    }
  }

  async function loadMessages(roomId, initial) {
    const after = initial ? 0 : CHAT.lastMsgIdByRoom[roomId] || 0;
    const q = new URLSearchParams({ room_id: String(roomId), after_id: String(after) });
    const { data } = await apiFetch(`/api/chat/messages?${q}`);
    if (!data.ok) {
      if (data.error === "room_not_found" || data.error === "no_permission") {
        await refreshBootstrap();
        const fallback = CHAT.bootstrap?.rooms?.find((r) => r.room_type === "global")?.id || CHAT.bootstrap?.active_room_id;
        if (fallback && Number(fallback) !== Number(CHAT.activeRoomId)) {
          await switchRoom(Number(fallback));
          return;
        }
      }
      showError(data.error || "no_permission");
      return;
    }
    const msgs = data.data?.messages || [];
    if (msgs.length) renderMessages(msgs, !initial);
    if (initial && msgs.length) {
      CHAT.lastMsgIdByRoom[roomId] = Number(msgs[msgs.length - 1].id);
    }
  }

  async function markRead() {
    if (!CHAT.activeRoomId) return;
    const lastId = CHAT.lastMsgIdByRoom[CHAT.activeRoomId] || 0;
    CHAT.unread[String(CHAT.activeRoomId)] = 0;
    CHAT.mentionUnread[String(CHAT.activeRoomId)] = false;
    updateFabBadge();
    renderRoomList();
    try {
      await apiFetch("/api/chat/read", {
        method: "POST",
        body: JSON.stringify({
          room_id: CHAT.activeRoomId,
          last_read_message_id: lastId,
        }),
      });
    } catch (_) {}
  }

  function renderRoomList() {
    if (!CHAT.roomList || !CHAT.bootstrap) return;
    CHAT.roomList.innerHTML = "";
    for (const room of CHAT.bootstrap.rooms || []) {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "gc-chat-room-btn";
      btn.dataset.roomId = room.id ? String(room.id) : "";
      if (room.disabled) {
        btn.disabled = true;
        btn.title = t("chat_no_alliance", "Keine Allianz");
      } else if (Number(room.id) === Number(CHAT.activeRoomId)) {
        btn.classList.add("is-active");
      }

      const label = document.createElement("span");
      label.className = "gc-chat-room-label";
      label.textContent = roomLabel(room);
      btn.appendChild(label);

      const unread = room.id ? Number(CHAT.unread[String(room.id)] || 0) : 0;
      const mention = room.id && CHAT.mentionUnread[String(room.id)];
      if (unread > 0 || mention) {
        const badge = document.createElement("span");
        badge.className = "gc-chat-room-badge" + (mention ? " is-mention" : "");
        badge.textContent = unread > 0 ? (unread > 9 ? "9+" : String(unread)) : "@";
        badge.title = mention ? t("chat_mentioned_you", "Erwähnung") : "";
        btn.appendChild(badge);
      }

      CHAT.roomList.appendChild(btn);
    }
  }

  function updateActiveRoomHeader() {
    const room = getActiveRoom();
    if (CHAT.activeTitle) CHAT.activeTitle.textContent = roomLabel(room);
    if (CHAT.roomHint) {
      if (room?.disabled) {
        CHAT.roomHint.textContent = t("chat_no_alliance", "Du bist in keiner Allianz.");
        CHAT.roomHint.hidden = false;
      } else {
        CHAT.roomHint.hidden = true;
        CHAT.roomHint.textContent = "";
      }
    }
    updateRoomToolsState(room);
    if (String(room?.room_type || "") === "custom" && room?.id) loadCustomRoomMembers(room.id);
    else if (CHAT.roomMembers) {
      CHAT.roomMembers.hidden = true;
      CHAT.roomMembers.textContent = "";
    }
  }

  function updateRoomToolsState(room) {
    const isCustom = String(room?.room_type || "") === "custom" && !!room?.id;
    const isOwner = String(room?.member_role || "") === "owner";
    if (CHAT.roomInviteBtn) CHAT.roomInviteBtn.disabled = !isCustom;
    if (CHAT.roomRemoveBtn) CHAT.roomRemoveBtn.disabled = !isCustom;
    if (CHAT.roomLeaveBtn) CHAT.roomLeaveBtn.disabled = !isCustom || isOwner;
    if (CHAT.roomDeleteBtn) {
      CHAT.roomDeleteBtn.disabled = !isCustom;
      CHAT.roomDeleteBtn.hidden = !isCustom;
      CHAT.roomDeleteBtn.title = isCustom
        ? t("chat_room_delete_confirm_named", "Raum \"{room}\" wirklich löschen?").replace("{room}", roomLabel(room))
        : t("chat_room_delete", "Raum löschen");
    }
  }

  async function loadCustomRoomMembers(roomId) {
    if (!CHAT.roomMembers) return;
    CHAT.roomMembers.hidden = false;
    CHAT.roomMembers.textContent = t("chat_room_members_loading", "Mitglieder laden…");
    const { data } = await apiFetch(`/api/chat/rooms/members?room_id=${encodeURIComponent(String(roomId))}`);
    if (!data.ok) {
      CHAT.roomMembers.textContent = t("chat_room_members_error", "Mitglieder konnten nicht geladen werden.");
      return;
    }
    const members = data.data?.members || [];
    const canManage = !!data.data?.can_manage;
    const canLeave = !!data.data?.can_leave;
    if (CHAT.roomInviteBtn) CHAT.roomInviteBtn.disabled = !canManage;
    if (CHAT.roomRemoveBtn) CHAT.roomRemoveBtn.disabled = !canManage;
    if (CHAT.roomLeaveBtn) CHAT.roomLeaveBtn.disabled = !canLeave;
    if (!members.length) {
      CHAT.roomMembers.textContent = t("chat_room_members_empty", "Keine Mitglieder.");
      return;
    }
    CHAT.roomMembers.textContent = members
      .map((m) => {
        const tags = [];
        if (m.role === "owner") tags.push(t("chat_room_owner", "Owner"));
        if (m.is_admin) tags.push(t("chat_admin", "Admin"));
        return tags.length ? `${m.name} (${tags.join(", ")})` : m.name;
      })
      .join(", ");
  }

  async function switchRoom(roomId) {
    if (!roomId || Number(roomId) === Number(CHAT.activeRoomId)) return;
    CHAT.activeRoomId = Number(roomId);
    CHAT.stickToBottom = true;
    CHAT.messagesEl.innerHTML = "";
    CHAT.pendingNew = 0;
    updateNewMsgsBtn();
    hideEmojiPicker();

    updateActiveRoomHeader();
    renderRoomList();
    debouncedSaveState({ active_room_id: CHAT.activeRoomId });
    await loadMessages(CHAT.activeRoomId, true);
    await markRead();
  }

  function notifyChatUnreadIfIncreased(before) {
    const after = totalUnread();
    if (after > before && !isChatPanelVisible()) {
      if (typeof GC.showNotify === "function") {
        GC.showNotify(t("chat_notify_new", "Neue Chat-Nachricht."), "info");
      }
    }
  }

  let _bootstrapAbort = null;
  let _initChatPromise = null;

  function abortBootstrapInFlight() {
    if (_bootstrapAbort) {
      try { _bootstrapAbort.abort(); } catch (_) {}
      _bootstrapAbort = null;
    }
    CHAT.polling.bootstrapInFlight = null;
  }

  function quiesceChat(reason) {
    stopPolling();
    abortBootstrapInFlight();
    _initChatPromise = null;
    if (reason) chatDebug("[chat] quiesce", reason);
  }

  async function refreshBootstrap() {
    abortBootstrapInFlight();
    const ctrl = new AbortController();
    _bootstrapAbort = ctrl;
    const beforeUnread = totalUnread();
    try {
      const { data } = await apiFetch("/api/chat/bootstrap", { signal: ctrl.signal });
      if (!data.ok) return false;
      CHAT.bootstrap = data.data;
      CHAT.unread = { ...(data.data.unread || {}) };
      CHAT.viewerName = data.data.player?.name || "";
      CHAT.viewerId = Number(data.data.player?.id) || 0;
      CHAT.uiState = mergeUiState(data.data.ui_state || {}, CHAT.uiState || {});
      saveLocalUiState(CHAT.uiState);
      if (!CHAT.activeRoomId) CHAT.activeRoomId = data.data.active_room_id;
      pruneRoomState();
      if (CHAT.activeRoomId && !(CHAT.bootstrap.rooms || []).some((r) => Number(r.id) === Number(CHAT.activeRoomId))) {
        CHAT.activeRoomId = Number(CHAT.bootstrap.active_room_id || 0) || null;
      }
      updateFabBadge();
      renderRoomList();
      notifyChatUnreadIfIncreased(beforeUnread);
      return true;
    } catch (err) {
      if (err?.name === "AbortError") return false;
      throw err;
    } finally {
      if (_bootstrapAbort === ctrl) _bootstrapAbort = null;
    }
  }

  async function bootstrap() {
    abortBootstrapInFlight();
    const ctrl = new AbortController();
    _bootstrapAbort = ctrl;
    try {
      const { data } = await apiFetch("/api/chat/bootstrap", { signal: ctrl.signal });
      if (!data.ok) {
        showError(data.error || "chat_not_ready");
        return false;
      }
      CHAT.bootstrap = data.data;
      const localState = loadLocalUiState();
      CHAT.uiState = mergeUiState(data.data.ui_state || {}, localState || {});
      CHAT.unread = { ...(data.data.unread || {}) };
      CHAT.viewerName = data.data.player?.name || "";
      CHAT.viewerId = Number(data.data.player?.id) || 0;
      CHAT.activeRoomId = data.data.active_room_id;
      CHAT.isMobile = window.matchMedia("(max-width: 768px)").matches;

      pruneRoomState();
      applyPanelGeometry(CHAT.uiState);
      saveLocalUiState(CHAT.uiState);
      updateFabBadge();
      renderRoomList();
      updateActiveRoomHeader();

      const ui = CHAT.uiState || {};
      const wantsOpen =
        GC._chatWantsOpen === true || (!CHAT.isMobile && ui.is_open && !ui.is_minimized);
      if (wantsOpen) {
        setOpen(true);
      } else {
        CHAT.root.classList.remove("is-open");
        CHAT.root.setAttribute("aria-hidden", "true");
        if (CHAT.fab) CHAT.fab.style.removeProperty("display");
      }

      if (CHAT.activeRoomId) {
        try {
          await loadMessages(CHAT.activeRoomId, true);
        } catch (err) {
          console.debug("[TChat] load messages", err);
        }
      }
      return true;
    } catch (err) {
      if (err?.name === "AbortError") return false;
      throw err;
    } finally {
      if (_bootstrapAbort === ctrl) _bootstrapAbort = null;
    }
  }

  function stopPolling() {
    CHAT.polling.started = false;
    if (CHAT.polling.timer) {
      clearTimeout(CHAT.polling.timer);
      CHAT.polling.timer = null;
    }
    if (CHAT.polling.abort) {
      try { CHAT.polling.abort.abort(); } catch (_) {}
      CHAT.polling.abort = null;
    }
  }

  function isPollTimerActive() {
    return CHAT.polling.started && !!CHAT.polling.timer;
  }

  async function maybeRefreshBootstrap(force = false) {
    const now = Date.now();
    const minGap = CHAT.polling.bootstrapIntervalMs || 60000;
    if (!force && CHAT.polling.lastBootstrapAt && (now - CHAT.polling.lastBootstrapAt) < minGap) {
      chatDebug("chat:bootstrap skipped/reused");
      return true;
    }
    if (CHAT.polling.bootstrapInFlight) {
      return CHAT.polling.bootstrapInFlight;
    }
    CHAT.polling.lastBootstrapAt = now;
    CHAT.polling.bootstrapInFlight = refreshBootstrap()
      .then((ok) => ok)
      .finally(() => {
        CHAT.polling.bootstrapInFlight = null;
      });
    return CHAT.polling.bootstrapInFlight;
  }

  function scheduleBootstrapRefresh(force = false) {
    maybeRefreshBootstrap(force).catch((e) => {
      if (e?.name !== "AbortError") chatDebug("[chat] bootstrap refresh", e);
    });
  }

  function clearPollTimer() {
    if (CHAT.polling.timer) {
      clearTimeout(CHAT.polling.timer);
      CHAT.polling.timer = null;
    }
    if (CHAT.polling.abort) {
      try { CHAT.polling.abort.abort(); } catch (_) {}
      CHAT.polling.abort = null;
    }
  }

  function pollDelayMs() {
    // Hidden tab first (battery / background), then closed panel, else active open poll.
    if (document.hidden) return CHAT.polling.intervalHidden;
    if (!isChatPanelVisible()) return CHAT.polling.intervalClosed;
    return CHAT.polling.interval;
  }

  function schedulePoll() {
    clearPollTimer();
    if (!CHAT.root || !CHAT.activeRoomId) return;
    CHAT.polling.started = true;
    CHAT.polling.timer = setTimeout(pollTick, pollDelayMs());
  }

  async function pollTick() {
    if (!CHAT.activeRoomId) {
      schedulePoll();
      return;
    }

    const panelVisible = isChatPanelVisible();
    const roomId = CHAT.activeRoomId;
    const after = CHAT.lastMsgIdByRoom[roomId] || 0;
    const ctrl = new AbortController();
    CHAT.polling.abort = ctrl;

    try {
      const q = new URLSearchParams({ room_id: String(roomId), after_id: String(after) });
      const res = await fetch(`/api/chat/messages?${q}`, {
        credentials: "same-origin",
        headers: { "X-Requested-With": "XMLHttpRequest" },
        signal: ctrl.signal,
      });
      const data = await res.json();
      chatDebug("[chat] poll", {
        roomId,
        after,
        ok: data.ok,
        count: data.data?.messages?.length || 0,
        panelVisible,
      });
      if (!data.ok) {
        if (data.error === "room_not_found" || data.error === "no_permission") {
          await maybeRefreshBootstrap(true);
          const fallback = CHAT.bootstrap?.rooms?.find((r) => r.room_type === "global")?.id || CHAT.bootstrap?.active_room_id;
          if (fallback && Number(fallback) !== Number(CHAT.activeRoomId)) {
            await switchRoom(Number(fallback));
            return;
          }
        }
      }
      if (data.ok && data.data?.messages?.length) {
        applyIncomingPollMessages(roomId, data.data.messages);
      }
    } catch (e) {
      if (e.name !== "AbortError") chatDebug("[chat] poll", e);
    } finally {
      CHAT.polling.abort = null;
      schedulePoll();
    }
  }

  function startPolling() {
    if (isPollTimerActive()) return;
    CHAT.polling.started = true;
    schedulePoll();
  }

  function resumeChatPolling() {
    if (!CHAT.root || !cacheElements()) return;
    if (!CHAT.bootstrap) return;
    if (isPollTimerActive()) return;
    CHAT.polling.started = true;
    schedulePoll();
  }

  async function sendMessage(text) {
    clearError();
    const body = String(text || "").trim();
    if (!body) {
      showError("empty_message");
      return;
    }
    if (body === "/clear") {
      if (CHAT.messagesEl) CHAT.messagesEl.innerHTML = "";
      if (CHAT.input) CHAT.input.value = "";
      return;
    }
    if (body === "/help") {
      showHelp();
      if (CHAT.input) CHAT.input.value = "";
      return;
    }

    const payload = { body };
    if (!body.startsWith("/") && CHAT.activeRoomId) payload.room_id = CHAT.activeRoomId;

    const { data } = await apiFetch("/api/chat/send", {
      method: "POST",
      body: JSON.stringify(payload),
    });

    if (!data.ok) {
      showError(data.error || "error");
      return;
    }

    const msg = data.data?.message;
    const roomId = data.data?.room_id;
    if (roomId && Number(roomId) !== Number(CHAT.activeRoomId)) {
      await refreshBootstrap();
      await switchRoom(roomId);
    } else if (msg) {
      renderMessages([msg], true);
      markRead();
    }
    if (CHAT.input) {
      CHAT.input.value = "";
      resizeInput();
    }
  }

  function showHelp() {
    const lines = [
      t("chat_cmd_w"),
      t("chat_cmd_r"),
      t("chat_cmd_a"),
      t("chat_cmd_g"),
      t("chat_cmd_me"),
      t("chat_cmd_room", "/room create|invite|kick"),
      t("chat_cmd_clear"),
      t("chat_cmd_help"),
    ];
    const wrap = document.createElement("div");
    wrap.className = "gc-chat-help";
    for (const line of lines) {
      const p = document.createElement("p");
      p.textContent = line;
      wrap.appendChild(p);
    }
    const row = document.createElement("article");
    row.className = "gc-chat-msg is-system";
    const body = document.createElement("div");
    body.className = "gc-chat-msg-body";
    body.appendChild(wrap);
    row.appendChild(body);
    CHAT.messagesEl?.appendChild(row);
    scrollToBottom(true);
  }

  function resizeInput() {
    if (!CHAT.input) return;
    CHAT.input.style.height = "auto";
    CHAT.input.style.height = `${Math.min(100, CHAT.input.scrollHeight)}px`;
  }

  async function whisperTo(playerId, playerName) {
    const pid = Number(playerId);
    const name = String(playerName || "").trim();
    if (!Number.isFinite(pid) || pid <= 0 || !name) return;

    setOpen(true);
    if (Number(pid) === CHAT.viewerId) {
      showError("cannot_whisper_self");
      return;
    }

    const { data } = await apiFetch("/api/chat/open-dm", {
      method: "POST",
      body: JSON.stringify({ target_player_id: pid }),
    });

    if (data.ok && data.data?.room_id) {
      await refreshBootstrap();
      await switchRoom(data.data.room_id);
      if (CHAT.input) {
        CHAT.input.value = "";
        CHAT.input.focus();
      }
      return;
    }

    if (CHAT.input) {
      CHAT.input.value = `/w ${name} `;
      CHAT.input.focus();
      resizeInput();
    }
  }

  async function createCustomRoomFromUI() {
    const title = window.prompt(t("chat_room_create_prompt", "Name des neuen Raums:"), "");
    if (!title) return;
    const { data } = await apiFetch("/api/chat/rooms/create", {
      method: "POST",
      body: JSON.stringify({ title: String(title).trim() }),
    });
    if (!data.ok) {
      showError(data.error || "error");
      return;
    }
    const roomId = Number(data.data?.room_id || data.data?.room?.id || 0);
    await refreshBootstrap();
    if (roomId > 0) await switchRoom(roomId);
    else renderRoomList();
  }

  async function inviteMemberFromUI() {
    const room = getActiveRoom();
    if (!room || String(room.room_type || "") !== "custom") {
      showError("no_permission");
      return;
    }
    const name = window.prompt(t("chat_room_invite_prompt", "Spielername zum Einladen:"), "");
    if (!name) return;
    const target = await resolvePlayerByName(name);
    if (!target) {
      showError("player_not_found");
      return;
    }
    const { data } = await apiFetch("/api/chat/rooms/invite", {
      method: "POST",
      body: JSON.stringify({ room_id: Number(room.id), player_id: Number(target.id) }),
    });
    if (!data.ok) {
      showError(data.error || "error");
      return;
    }
    await loadCustomRoomMembers(Number(room.id));
  }

  async function removeMemberFromUI() {
    const room = getActiveRoom();
    if (!room || String(room.room_type || "") !== "custom") {
      showError("no_permission");
      return;
    }
    const name = window.prompt(t("chat_room_remove_prompt", "Spielername zum Entfernen:"), "");
    if (!name) return;
    const target = await resolvePlayerByName(name);
    if (!target) {
      showError("player_not_found");
      return;
    }
    const { data } = await apiFetch("/api/chat/rooms/remove", {
      method: "POST",
      body: JSON.stringify({ room_id: Number(room.id), player_id: Number(target.id) }),
    });
    if (!data.ok) {
      showError(data.error || "error");
      return;
    }
    await loadCustomRoomMembers(Number(room.id));
  }

  async function deleteRoomFromUI() {
    const room = getActiveRoom();
    if (!room || String(room.room_type || "") !== "custom") {
      showError("no_permission");
      return;
    }
    const ok = window.confirm(
      t("chat_room_delete_confirm_named", "Raum \"{room}\" wirklich löschen?").replace("{room}", roomLabel(room))
    );
    if (!ok) return;
    const { data } = await apiFetch("/api/chat/rooms/delete", {
      method: "POST",
      body: JSON.stringify({ room_id: Number(room.id) }),
    });
    if (!data.ok) {
      showError(data.error || "error");
      return;
    }
    delete CHAT.unread[String(room.id)];
    delete CHAT.mentionUnread[String(room.id)];
    delete CHAT.lastMsgIdByRoom[String(room.id)];
    await refreshBootstrap();
    const fallback = CHAT.bootstrap?.rooms?.find((r) => r.room_type === "global")?.id || CHAT.bootstrap?.active_room_id;
    if (fallback) await switchRoom(Number(fallback));
    else renderRoomList();
  }

  async function leaveRoomFromUI() {
    const room = getActiveRoom();
    if (!room || String(room.room_type || "") !== "custom") {
      showError("no_permission");
      return;
    }
    const { data } = await apiFetch("/api/chat/rooms/leave", {
      method: "POST",
      body: JSON.stringify({ room_id: Number(room.id) }),
    });
    if (!data.ok) {
      showError(data.error || "error");
      return;
    }
    delete CHAT.unread[String(room.id)];
    delete CHAT.mentionUnread[String(room.id)];
    delete CHAT.lastMsgIdByRoom[String(room.id)];
    await refreshBootstrap();
    const fallback = CHAT.bootstrap?.rooms?.find((r) => r.room_type === "global")?.id || CHAT.bootstrap?.active_room_id;
    if (fallback) await switchRoom(Number(fallback));
  }

  async function resolvePlayerByName(rawName) {
    const q = String(rawName || "").trim();
    if (!q) return null;
    const { data } = await apiFetch(`/api/chat/players?q=${encodeURIComponent(q)}`);
    if (!data.ok) return null;
    const players = data.data?.players || [];
    if (!players.length) return null;
    const exact = players.find((p) => String(p.name || "").toLowerCase() === q.toLowerCase());
    return exact || players[0] || null;
  }

  let acTimer = null;
  async function handleAutocomplete() {
    const val = CHAT.input?.value || "";
    const mW = val.match(/^\/w(?:hisper)?\s+(\S*)$/i);
    const mAt = val.match(/@(\S*)$/);
    const q = (mW && mW[1]) || (mAt && mAt[1]);
    if (!q || q.length < 1) {
      hideAutocomplete();
      return;
    }
    clearTimeout(acTimer);
    acTimer = setTimeout(async () => {
      const { data } = await apiFetch(`/api/chat/players?q=${encodeURIComponent(q)}`);
      if (!data.ok) return;
      showAutocomplete(data.data?.players || [], (pick) => {
        if (mW) CHAT.input.value = `/w ${pick} `;
        else if (mAt) CHAT.input.value = val.replace(/@\S*$/, `@${pick} `);
        hideAutocomplete();
        CHAT.input.focus();
      });
    }, 200);
  }

  function hideAutocomplete() {
    if (!CHAT.autocompleteEl) return;
    CHAT.autocompleteEl.hidden = true;
    CHAT.autocompleteEl.innerHTML = "";
  }

  function showAutocomplete(players, onPick) {
    if (!CHAT.autocompleteEl) return;
    CHAT.autocompleteEl.innerHTML = "";
    if (!players.length) {
      CHAT.autocompleteEl.hidden = true;
      return;
    }
    for (const p of players) {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "gc-chat-ac-item";
      btn.textContent = p.name;
      btn.addEventListener("click", () => onPick(p.name));
      CHAT.autocompleteEl.appendChild(btn);
    }
    CHAT.autocompleteEl.hidden = false;
  }

  function hideEmojiPicker() {
    if (!CHAT.emojiPicker) return;
    CHAT.emojiPicker.hidden = true;
    CHAT.emojiToggle?.classList.remove("is-open");
  }

  function toggleEmojiPicker() {
    if (!CHAT.emojiPicker) return;
    const open = CHAT.emojiPicker.hidden;
    hideAutocomplete();
    if (open) {
      CHAT.emojiPicker.hidden = false;
      CHAT.emojiToggle?.classList.add("is-open");
    } else {
      hideEmojiPicker();
    }
  }

  function insertEmoji(emoji) {
    if (!CHAT.input) return;
    const val = CHAT.input.value || "";
    const start = CHAT.input.selectionStart ?? val.length;
    const end = CHAT.input.selectionEnd ?? val.length;
    const next = val.slice(0, start) + emoji + val.slice(end);
    if (next.length > 500) return;
    CHAT.input.value = next;
    const pos = start + emoji.length;
    CHAT.input.setSelectionRange(pos, pos);
    CHAT.input.focus();
    resizeInput();
    hideEmojiPicker();
  }

  function initEmojiPicker() {
    if (!CHAT.emojiPicker || CHAT.emojiPicker.childElementCount) return;
    for (const emoji of CHAT_EMOJIS) {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "gc-chat-emoji-item";
      btn.textContent = emoji;
      btn.setAttribute("aria-label", emoji);
      btn.addEventListener("click", (e) => {
        e.preventDefault();
        e.stopPropagation();
        insertEmoji(emoji);
      });
      CHAT.emojiPicker.appendChild(btn);
    }
  }

  function initDragResize() {
    const handle = qs("[data-chat-drag-handle]");
    const resizeEl = qs("[data-chat-resize]");
    if (!handle || !CHAT.panel || CHAT.isMobile || CHAT.dragBound) return;

    handle.addEventListener("pointerdown", (e) => {
      if (e.button !== 0 || CHAT.isMaximized) return;
      if (e.target.closest(".gc-chat-header-actions, .gc-chat-btn, [data-chat-minimize], [data-chat-maximize], [data-chat-close]")) {
        return;
      }
      e.preventDefault();
      const rect = CHAT.panel.getBoundingClientRect();
      CHAT.useCustomPosition = true;
      CHAT.panel.classList.add("is-custom-pos");
      CHAT.panel.style.right = "auto";
      CHAT.panel.style.bottom = "auto";
      CHAT.panel.style.left = `${rect.left}px`;
      CHAT.panel.style.top = `${rect.top}px`;
      CHAT.drag = {
        startX: e.clientX,
        startY: e.clientY,
        left: rect.left,
        top: rect.top,
      };
      handle.setPointerCapture(e.pointerId);
    });

    handle.addEventListener("pointermove", (e) => {
      if (!CHAT.drag) return;
      const dx = e.clientX - CHAT.drag.startX;
      const dy = e.clientY - CHAT.drag.startY;
      CHAT.panel.style.left = `${CHAT.drag.left + dx}px`;
      CHAT.panel.style.top = `${CHAT.drag.top + dy}px`;
      clampPanelToViewport();
    });

    const endDrag = () => {
      if (!CHAT.drag) return;
      CHAT.drag = null;
      CHAT.useCustomPosition = true;
      persistState(readPanelStateForSave(), true);
    };
    handle.addEventListener("pointerup", endDrag);
    handle.addEventListener("pointercancel", endDrag);

    if (!resizeEl) return;
    resizeEl.addEventListener("pointerdown", (e) => {
      if (CHAT.isMaximized) return;
      e.preventDefault();
      CHAT.resize = {
        startX: e.clientX,
        startY: e.clientY,
        w: CHAT.panel.offsetWidth,
        h: CHAT.panel.offsetHeight,
      };
      resizeEl.setPointerCapture(e.pointerId);
    });
    resizeEl.addEventListener("pointermove", (e) => {
      if (!CHAT.resize) return;
      const vp = getViewportBounds();
      const maxW = vp.width;
      const maxH = vp.height;
      const w = Math.max(MIN_W, Math.min(MAX_W, Math.min(maxW, CHAT.resize.w + (e.clientX - CHAT.resize.startX))));
      const h = Math.max(MIN_H, Math.min(maxH, CHAT.resize.h + (e.clientY - CHAT.resize.startY)));
      CHAT.panel.style.width = `${w}px`;
      CHAT.panel.style.height = `${h}px`;
      clampPanelToViewport();
    });
    const endResize = () => {
      if (!CHAT.resize) return;
      CHAT.resize = null;
      persistState(readPanelStateForSave(), true);
    };
    resizeEl.addEventListener("pointerup", endResize);
    resizeEl.addEventListener("pointercancel", endResize);

    window.addEventListener("resize", () => {
      if (!CHAT.isMaximized) clampPanelToViewport();
    });
  }

  function cacheElements() {
    CHAT.root = document.getElementById("gc-chat-root");
    if (!CHAT.root) return false;
    CHAT.panel = qs("[data-chat-panel]");
    CHAT.fab = qs("[data-chat-fab]");
    CHAT.roomList = qs("[data-chat-room-list]");
    CHAT.messagesEl = qs("[data-chat-messages]");
    CHAT.input = qs("[data-chat-input]");
    CHAT.errorEl = qs("[data-chat-error]");
    CHAT.newMsgsBtn = qs("[data-chat-new-msgs]");
    CHAT.autocompleteEl = qs("[data-chat-autocomplete]");
    CHAT.activeTitle = qs("[data-chat-active-title]");
    CHAT.roomHint = qs("[data-chat-room-hint]");
    CHAT.roomMembers = qs("[data-chat-room-members]");
    CHAT.fabBadge = qs("[data-chat-fab-badge]");
    CHAT.maximizeBtn = qs("[data-chat-maximize]");
    CHAT.emojiToggle = qs("[data-chat-emoji-toggle]");
    CHAT.emojiPicker = qs("[data-chat-emoji-picker]");
    CHAT.roomCreateBtn = qs("[data-chat-room-create]");
    CHAT.roomInviteBtn = qs("[data-chat-room-invite]");
    CHAT.roomRemoveBtn = qs("[data-chat-room-remove]");
    CHAT.roomLeaveBtn = qs("[data-chat-room-leave]");
    CHAT.roomDeleteBtn = qs("[data-chat-room-delete]");
    return true;
  }

  function getChatRoot() {
    return document.getElementById("gc-chat-root");
  }

  /** Document-level open/close — survives PJAX and runs before bootstrap. */
  function installGlobalChatHandlers() {
    if (CHAT.uiBound) return;
    CHAT.uiBound = true;
    chatDebug("chat:bound");

    document.addEventListener("click", (e) => {
      const specialChatBtn = e.target.closest("[data-special-open-window='chat']");
      if (specialChatBtn) {
        e.preventDefault();
        e.stopPropagation();
        chatDebug("chat:open");
        void openTChat();
        return;
      }

      const fab = e.target.closest("[data-chat-fab]");
      if (fab) {
        const root = getChatRoot();
        if (!root || !root.contains(fab)) return;
        e.preventDefault();
        e.stopPropagation();
        chatDebug("chat:open");
        void openTChat();
        return;
      }

      const root = getChatRoot();
      if (!root) return;
      const panel = e.target.closest(".gc-chat-panel");
      if (!panel || !root.contains(panel)) return;

      if (e.target.closest("[data-chat-minimize]") || e.target.closest("[data-chat-close]")) {
        e.preventDefault();
        e.stopPropagation();
        if (!cacheElements()) return;
        if (CHAT.isMaximized) {
          CHAT.isMaximized = false;
          CHAT.root.classList.remove("is-maximized");
        }
        setMinimized();
        return;
      }
      if (e.target.closest("[data-chat-maximize]")) {
        e.preventDefault();
        e.stopPropagation();
        if (!cacheElements()) return;
        toggleMaximize();
      }
    });

    if (!CHAT.whisperBound) {
      CHAT.whisperBound = true;
      document.addEventListener("click", (e) => {
        const w = e.target.closest("[data-chat-whisper]");
        if (!w) return;
        e.preventDefault();
        e.stopPropagation();
        const pid = w.dataset.playerId;
        const pname = w.dataset.playerName || w.textContent?.trim();
        if (pid) whisperTo(Number(pid), pname);
      });
    }

    if (!CHAT.emojiDismissBound) {
      CHAT.emojiDismissBound = true;
      document.addEventListener("click", (e) => {
        if (!CHAT.emojiPicker || CHAT.emojiPicker.hidden) return;
        if (e.target.closest("[data-chat-emoji-toggle], [data-chat-emoji-picker]")) return;
        hideEmojiPicker();
      });
    }

    if (!CHAT.lifecycleBound) {
      CHAT.lifecycleBound = true;
      document.addEventListener("visibilitychange", () => {
        if (document.hidden) persistState(readPanelStateForSave(), true);
        schedulePoll();
      });
      window.addEventListener("beforeunload", () => {
        try {
          const body = {
            ...(CHAT.uiState || {}),
            ...readPanelStateForSave(),
            version: STATE_VERSION,
            saved_at: Math.floor(Date.now() / 1000),
            is_open: CHAT.root?.classList.contains("is-open"),
            is_minimized: !CHAT.root?.classList.contains("is-open"),
            active_room_id: CHAT.activeRoomId,
          };
          CHAT.uiState = sanitizeUiState(body);
          saveLocalUiState(CHAT.uiState);
        } catch (_) {}
      });
    }
  }

  function bindRootEvents() {
    if (!CHAT.root || CHAT.rootEventsBound) return;
    CHAT.rootEventsBound = true;

    CHAT.root.addEventListener(
      "pointerdown",
      (e) => {
        if (e.target.closest("[data-chat-minimize], [data-chat-maximize], [data-chat-close], .gc-chat-header-actions")) {
          e.stopPropagation();
        }
      },
      true
    );

    qs("[data-chat-composer]")?.addEventListener("submit", (e) => {
      e.preventDefault();
      sendMessage(CHAT.input?.value);
    });

    CHAT.input?.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        sendMessage(CHAT.input.value);
      }
    });
    CHAT.input?.addEventListener("input", () => {
      resizeInput();
      handleAutocomplete();
      hideEmojiPicker();
    });

    CHAT.emojiToggle?.addEventListener("click", (e) => {
      e.preventDefault();
      e.stopPropagation();
      toggleEmojiPicker();
    });

    CHAT.messagesEl?.addEventListener("scroll", () => {
      CHAT.stickToBottom = isNearBottom();
      if (CHAT.stickToBottom) {
        CHAT.pendingNew = 0;
        updateNewMsgsBtn();
        markRead();
      }
    });

    CHAT.newMsgsBtn?.addEventListener("click", () => scrollToBottom(true));

    CHAT.roomList?.addEventListener("click", (e) => {
      const btn = e.target.closest(".gc-chat-room-btn");
      if (!btn || btn.disabled || !btn.dataset.roomId) return;
      switchRoom(Number(btn.dataset.roomId));
    });

    CHAT.roomCreateBtn?.addEventListener("click", (e) => {
      e.preventDefault();
      createCustomRoomFromUI();
    });
    CHAT.roomInviteBtn?.addEventListener("click", (e) => {
      e.preventDefault();
      inviteMemberFromUI();
    });
    CHAT.roomRemoveBtn?.addEventListener("click", (e) => {
      e.preventDefault();
      removeMemberFromUI();
    });
    CHAT.roomLeaveBtn?.addEventListener("click", (e) => {
      e.preventDefault();
      leaveRoomFromUI();
    });
    CHAT.roomDeleteBtn?.addEventListener("click", (e) => {
      e.preventDefault();
      deleteRoomFromUI();
    });

    CHAT.messagesEl?.addEventListener("click", (e) => {
      const sender = e.target.closest(".gc-chat-msg-sender");
      if (!sender) return;
      whisperTo(sender.dataset.playerId, sender.dataset.playerName);
    });
  }

  async function runInitialBootstrap() {
    if (GC._chatBootstrapDone && CHAT.bootstrap) {
      chatDebug("chat:bootstrap skipped/reused");
      return true;
    }
    chatDebug("chat:bootstrap load");
    const ok = await bootstrap();
    if (ok) {
      GC._chatBootstrapDone = true;
      CHAT.polling.lastBootstrapAt = Date.now();
    }
    return ok;
  }

  async function initChatCore() {
    if (!getChatRoot()) {
      chatDebug("chat:init skipped (no root)");
      return false;
    }
    installGlobalChatHandlers();
    if (!cacheElements()) {
      chatDebug("chat:init skipped (cache)");
      return false;
    }
    chatDebug("chat:init");
    CHAT.isMobile = window.matchMedia("(max-width: 768px)").matches;
    bindRootEvents();
    initEmojiPicker();
    if (!CHAT.dragBound) {
      initDragResize();
      CHAT.dragBound = true;
    }
    CHAT.root.hidden = false;
    CHAT.root.removeAttribute("hidden");

    const ok = await runInitialBootstrap();
    if (ok) startPolling();

    if (!GC._chatCleanupRegistered && typeof GC.registerCleanup === "function") {
      GC._chatCleanupRegistered = true;
      GC.registerCleanup(() => {
        stopPolling();
      }, { persistent: true });
    }
    return ok;
  }

  function initChat() {
    installGlobalChatHandlers();
    if (!getChatRoot()) return Promise.resolve(false);

    if (GC._chatBootstrapDone) {
      if (cacheElements()) bindRootEvents();
      resumeChatPolling();
      return Promise.resolve(true);
    }

    if (_initChatPromise) {
      if (cacheElements()) bindRootEvents();
      return _initChatPromise;
    }

    _initChatPromise = initChatCore()
      .catch((err) => {
        console.error("[chat] init failed", err);
        _initChatPromise = null;
        return false;
      })
      .then((ok) => {
        if (!ok) _initChatPromise = null;
        return ok;
      });
    return _initChatPromise;
  }

  async function openTChat() {
    if (!getChatRoot()) return;
    chatDebug("chat:open");
    installGlobalChatHandlers();
    if (!cacheElements()) return;
    GC._chatWantsOpen = true;
    setOpen(true);
    try {
      await initChat();
    } catch (err) {
      console.error("[chat] openTChat init failed", err);
    }
    if (GC._chatWantsOpen && getChatRoot()) {
      if (!CHAT.root) cacheElements();
      setOpen(true);
    }
  }

  installGlobalChatHandlers();

  GC.initChat = initChat;
  GC.openTChat = openTChat;
  GC.resumeChatPolling = resumeChatPolling;
  GC.stopChatPolling = stopPolling;
  GC.quiesceChat = quiesceChat;
  GC.TChat = CHAT;
  GC.whisperPlayer = whisperTo;

  async function openAllianceChat() {
    await openTChat();
    const findAllianceRoom = () =>
      (CHAT.bootstrap?.rooms || []).find(
        (r) => String(r.room_type || "") === "alliance" && r.id && !r.disabled
      );
    let room = findAllianceRoom();
    if (!room) {
      await refreshBootstrap();
      room = findAllianceRoom();
    }
    if (room) await switchRoom(Number(room.id));
  }
  GC.openAllianceChat = openAllianceChat;
})();
