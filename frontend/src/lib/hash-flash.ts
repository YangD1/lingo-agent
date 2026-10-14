import { useEffect } from "react";

/** How long the ring stays (matches `section-flash` in globals.css). */
export const FLASH_MS = 1800;
/** A card may render after the page (it loads its data first): look for it this long. */
export const FIND_FOR_MS = 5000;
const FIND_EVERY_MS = 100;

/**
 * Scrolls to the element the hash names and rings it briefly (ADR 0039 §1: the desk pet
 * leads to a settings card). Waits for it when it isn't there yet; gives up after
 * `FIND_FOR_MS`, say for a card this learner doesn't get. Returns a cancel function.
 */
export function flashHashTarget(hash: string): () => void {
  const id = decodeURIComponent(hash.replace(/^#/, ""));
  if (!id) return () => {};
  let timer: ReturnType<typeof setTimeout> | undefined;
  const started = Date.now();
  const find = () => {
    const el = document.getElementById(id);
    if (!el) {
      if (Date.now() - started < FIND_FOR_MS) timer = setTimeout(find, FIND_EVERY_MS);
      return;
    }
    const still = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    el.scrollIntoView?.({ block: "start", behavior: still ? "auto" : "smooth" });
    // Again from the start when it was already ringing.
    delete el.dataset.flash;
    void el.offsetWidth;
    el.dataset.flash = "";
    timer = setTimeout(() => delete el.dataset.flash, FLASH_MS);
  };
  find();
  return () => clearTimeout(timer);
}

/**
 * Rings what the URL's hash names on arrival, and again whenever a link changes the hash
 * (Next.js changes it with pushState, which fires no `hashchange`: clicks are watched).
 */
export function useHashFlash() {
  useEffect(() => {
    let cancel = flashHashTarget(window.location.hash);
    let last = window.location.hash;
    const check = () => {
      if (window.location.hash === last) return;
      last = window.location.hash;
      cancel();
      cancel = flashHashTarget(last);
    };
    // After the click is handled, the URL has its new hash. A link to the hash already in
    // the URL changes nothing, yet was asked for: ring it again.
    const onClick = (e: MouseEvent) => {
      const link = e.target instanceof Element ? e.target.closest("a[href*='#']") : null;
      const href = link instanceof HTMLAnchorElement ? link.href : null;
      setTimeout(() => {
        if (href && href === window.location.href) last = "";
        check();
      }, 0);
    };
    window.addEventListener("hashchange", check);
    window.addEventListener("popstate", check);
    document.addEventListener("click", onClick);
    return () => {
      cancel();
      window.removeEventListener("hashchange", check);
      window.removeEventListener("popstate", check);
      document.removeEventListener("click", onClick);
    };
  }, []);
}
