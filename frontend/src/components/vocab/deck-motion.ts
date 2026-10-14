/**
 * The flashcard deck's motion (ADR 0038): the card turns over, flies off when rated, and the
 * next rises from the pile. Web Animations on the card element, no animation library. With
 * "reduce motion" each becomes a fade. Where `animate` is missing (jsdom) nothing plays and
 * callers change state at once.
 */

const EASE_OUT = "cubic-bezier(0.2, 0.8, 0.2, 1)";

export function canAnimate(el: HTMLElement | null): el is HTMLElement {
  return el !== null && typeof el.animate === "function";
}

function reduced(): boolean {
  return window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false;
}

async function done(animation: Animation): Promise<void> {
  try {
    await animation.finished;
  } catch {
    // Cancelled: whoever cancelled it has moved on.
  }
}

/** First half of a turn: the face goes edge-on (or fades). */
export function turnAway(el: HTMLElement): Promise<void> {
  return done(
    reduced()
      ? el.animate([{ opacity: 1 }, { opacity: 0 }], { duration: 100, fill: "forwards" })
      : el.animate([{ transform: "perspective(1400px) rotateY(0deg)" }, { transform: "perspective(1400px) rotateY(90deg)" }], {
          duration: 140,
          easing: "ease-in",
          fill: "forwards",
        }),
  );
}

/** Second half: the other side comes round. Replaces the first half's held frame. */
export function turnBack(el: HTMLElement): void {
  for (const a of el.getAnimations()) a.cancel();
  if (reduced()) el.animate([{ opacity: 0 }, { opacity: 1 }], { duration: 140 });
  else
    el.animate([{ transform: "perspective(1400px) rotateY(-90deg)" }, { transform: "perspective(1400px) rotateY(0deg)" }], {
      duration: 200,
      easing: EASE_OUT,
    });
}

/**
 * The rated card leaves: left for Again, right otherwise, from wherever a swipe left it.
 * Holds its last frame until `rise` (or `comeBack`) replaces it.
 */
export function flyOff(el: HTMLElement, direction: -1 | 1): void {
  const from = el.style.transform || "none";
  el.style.transform = "";
  if (reduced()) {
    el.animate([{ opacity: 1 }, { opacity: 0 }], { duration: 150, fill: "forwards" });
    return;
  }
  el.animate(
    [
      { transform: from, opacity: 1 },
      { transform: `translateX(${direction * 125}%) rotate(${direction * 14}deg)`, opacity: 0 },
    ],
    { duration: 280, easing: "ease-in", fill: "forwards" },
  );
}

/** The next card comes up off the pile behind (or fades in). */
export function rise(el: HTMLElement): void {
  for (const a of el.getAnimations()) a.cancel();
  if (reduced()) {
    el.animate([{ opacity: 0 }, { opacity: 1 }], { duration: 160 });
    return;
  }
  el.animate(
    [
      { transform: "translateY(18px) scale(0.94) rotate(2.5deg)", opacity: 0.4 },
      { transform: "none", opacity: 1 },
    ],
    { duration: 320, easing: EASE_OUT },
  );
}

/** A round done: the last card settles with a small pop. */
export function settle(el: HTMLElement): void {
  for (const a of el.getAnimations()) a.cancel();
  if (reduced()) {
    el.animate([{ opacity: 0 }, { opacity: 1 }], { duration: 200 });
    return;
  }
  el.animate(
    [
      { transform: "scale(0.9)", opacity: 0 },
      { transform: "scale(1.03)", opacity: 1, offset: 0.6 },
      { transform: "none", opacity: 1 },
    ],
    { duration: 480, easing: EASE_OUT },
  );
}

/**
 * A swipe let go short of rating, or a rating that failed to save: back to the middle.
 * Without animations it just snaps back.
 */
export function comeBack(el: HTMLElement): void {
  const from = el.style.transform || null;
  el.style.transform = "";
  if (!canAnimate(el)) return;
  for (const a of el.getAnimations()) a.cancel();
  if (from) el.animate([{ transform: from }, { transform: "none" }], { duration: 220, easing: EASE_OUT });
  else rise(el);
}
