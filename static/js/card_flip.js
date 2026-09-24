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

  function setFlipped(card, flipped) {
    if (!card) return;
    var on = !!flipped;
    card.classList.toggle("is-flipped", on);
    card.setAttribute("data-card-flip-state", on ? "back" : "front");

    card.querySelectorAll("[data-card-flip-trigger]").forEach(function (trigger) {
      trigger.setAttribute("aria-pressed", on ? "true" : "false");
    });

    var front = card.querySelector("[data-card-flip-front]");
    var back = card.querySelector("[data-card-flip-back]");
    if (front) front.setAttribute("aria-hidden", on ? "true" : "false");
    if (back) back.setAttribute("aria-hidden", on ? "false" : "true");
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
    if (trigger.hasAttribute("data-card-flip-back-trigger")) setFlipped(card, false);
    else toggleFrom(trigger);
  });

  GC.setCardFlipped = setFlipped;
})(window);
