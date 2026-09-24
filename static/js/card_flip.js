/**
 * GC-FERDI-FLIP-002 — shared progression card flip controller.
 * Artwork is the only front-face trigger; build/research/train actions stay independent.
 */
(function (global) {
  "use strict";

  var GC = global.GC || (global.GC = {});
  if (GC.cardFlipBound) return;
  GC.cardFlipBound = true;

  function cardFor(node) {
    return node && node.closest ? node.closest("[data-card-flip]") : null;
  }

  function faceHeight(face) {
    if (!face) return 0;
    return Math.max(face.scrollHeight || 0, Math.ceil(face.getBoundingClientRect().height || 0));
  }

  function sizeStageFor(card, flipped) {
    if (!card) return;
    var stage = card.querySelector("[data-card-flip-stage]");
    var face = card.querySelector(flipped ? "[data-card-flip-back]" : "[data-card-flip-front]");
    if (!stage || !face) return;

    var height = faceHeight(face);
    if (height > 0) {
      stage.style.height = height + "px";
    }

    if (!flipped) {
      window.setTimeout(function () {
        if (!card.classList.contains("is-flipped")) {
          stage.style.height = "";
        }
      }, 320);
    }
  }

  function setFlipped(card, flipped) {
    if (!card) return;
    var on = !!flipped;
    var front = card.querySelector("[data-card-flip-front]");
    var back = card.querySelector("[data-card-flip-back]");

    sizeStageFor(card, on);
    card.classList.toggle("is-flipped", on);
    card.setAttribute("data-card-flip-state", on ? "back" : "front");

    card.querySelectorAll("[data-card-flip-trigger]").forEach(function (trigger) {
      trigger.setAttribute("aria-pressed", on ? "true" : "false");
    });

    if (front) {
      front.setAttribute("aria-hidden", on ? "true" : "false");
      front.inert = on;
    }
    if (back) {
      back.setAttribute("aria-hidden", on ? "false" : "true");
      back.inert = !on;
    }

    requestAnimationFrame(function () {
      sizeStageFor(card, on);
    });
  }

  function toggleFrom(node) {
    var card = cardFor(node);
    if (!card) return;
    setFlipped(card, !card.classList.contains("is-flipped"));
  }

  document.addEventListener("click", function (event) {
    var back = event.target.closest("[data-card-flip-back-trigger]");
    if (back) {
      var backCard = cardFor(back);
      if (backCard) {
        event.preventDefault();
        event.stopPropagation();
        setFlipped(backCard, false);
      }
      return;
    }

    var trigger = event.target.closest("[data-card-flip-trigger]");
    if (!trigger) return;
    var card = cardFor(trigger);
    if (!card) return;
    event.preventDefault();
    event.stopPropagation();
    toggleFrom(trigger);
  });

  document.addEventListener("keydown", function (event) {
    if (event.key !== "Enter" && event.key !== " ") return;
    var trigger = event.target.closest("[data-card-flip-trigger], [data-card-flip-back-trigger]");
    if (!trigger) return;
    var card = cardFor(trigger);
    if (!card) return;
    event.preventDefault();
    if (trigger.hasAttribute("data-card-flip-back-trigger")) {
      setFlipped(card, false);
      var artwork = card.querySelector("[data-card-flip-trigger]");
      if (artwork) requestAnimationFrame(function () { artwork.focus(); });
    } else {
      toggleFrom(trigger);
      var backButton = card.querySelector("[data-card-flip-back-trigger]");
      if (backButton && card.classList.contains("is-flipped")) {
        requestAnimationFrame(function () { backButton.focus(); });
      }
    }
  });

  window.addEventListener("resize", function () {
    document.querySelectorAll("[data-card-flip].is-flipped").forEach(function (card) {
      sizeStageFor(card, true);
    });
  });

  GC.setCardFlipped = setFlipped;
  GC.syncCardFlipHeight = function (card) {
    sizeStageFor(card, !!(card && card.classList.contains("is-flipped")));
  };
})(window);
