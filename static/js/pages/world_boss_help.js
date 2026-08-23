/* World Boss help modal top-layer portal. UI only; no gameplay state changes. */
(() => {
  "use strict";

  const origins = new WeakMap();

  function portalModal(modal) {
    if (!modal || modal.parentElement === document.body) return;
    origins.set(modal, { parent: modal.parentNode, next: modal.nextSibling });
    document.body.appendChild(modal);
  }

  function restoreModal(modal) {
    const origin = modal ? origins.get(modal) : null;
    if (!modal || !origin) return;
    if (!origin.parent || !origin.parent.isConnected) {
      modal.remove();
      origins.delete(modal);
      return;
    }
    if (origin.next && origin.next.parentNode === origin.parent) {
      origin.parent.insertBefore(modal, origin.next);
    } else {
      origin.parent.appendChild(modal);
    }
    origins.delete(modal);
  }

  function helpModal() {
    return document.getElementById("wb-help-modal");
  }

  function restoreWhenClosed(modal) {
    window.setTimeout(() => {
      if (!modal) return;
      const closed = modal.hidden || modal.getAttribute("aria-hidden") === "true";
      if (closed) restoreModal(modal);
    }, 0);
  }

  document.addEventListener("click", (event) => {
    const target = event.target instanceof Element ? event.target : null;
    if (!target) return;

    if (target.closest("#wb-help-open")) {
      portalModal(helpModal());
      return;
    }

    if (target.closest("[data-wb-help-close]")) {
      restoreWhenClosed(helpModal());
      return;
    }

    if (target.closest("a[data-pjax-link]")) {
      const modal = helpModal();
      if (modal && origins.has(modal)) restoreModal(modal);
    }
  }, true);

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") restoreWhenClosed(helpModal());
  });
})();
