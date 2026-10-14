"use client";

import { useSearchParams } from "next/navigation";
import { useCallback, useEffect, useRef } from "react";

import { ReviewDeck } from "./review-deck";
import type { ReviewMode } from "./use-review-session";

/** Where every way into flashcards links to; opened directly, it redirects to the overlay. */
export const REVIEW_PATH = "/vocab/review";
const PARAM = "review";

function parseMode(value: string | null): ReviewMode | null {
  return value === "all" || value === "new" ? value : null;
}

/**
 * The link click to open as the overlay instead: a plain left click on a same-origin link to
 * `/vocab/review` (Q75d). A modifier, another button, or another target opens it as a page
 * (which redirects to the overlay there). Returns the mode it asks for.
 */
export function reviewLinkMode(event: MouseEvent): ReviewMode | null {
  if (event.defaultPrevented || event.button !== 0) return null;
  if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return null;
  const link = event.target instanceof Element ? event.target.closest("a[href]") : null;
  if (!(link instanceof HTMLAnchorElement)) return null;
  if ((link.target && link.target !== "_self") || link.hasAttribute("download")) return null;
  const url = new URL(link.href, window.location.href);
  if (url.origin !== window.location.origin || url.pathname !== REVIEW_PATH) return null;
  return url.searchParams.get("mode") === "new" ? "new" : "all";
}

function urlWith(mode: ReviewMode | null): URL {
  const url = new URL(window.location.href);
  if (mode) url.searchParams.set(PARAM, mode);
  else url.searchParams.delete(PARAM);
  return url;
}

/**
 * Shows flashcards over the current page while it has `?review=all|new` (ADR 0038). Links
 * to `/vocab/review` anywhere in the app open it in place, through the native history API:
 * Next.js syncs that to `useSearchParams` without asking the server for the page again, so
 * the page underneath keeps its state, and Back closes the overlay.
 */
export function ReviewDeckHost() {
  const mode = parseMode(useSearchParams().get(PARAM));
  // Opened from a link on this page, so there is an entry without the overlay to go back to.
  const pushed = useRef(false);
  useEffect(() => {
    if (!mode) pushed.current = false;
  }, [mode]);

  useEffect(() => {
    function onClick(event: MouseEvent) {
      const wanted = reviewLinkMode(event);
      if (!wanted) return;
      event.preventDefault();
      event.stopPropagation();
      if (new URL(window.location.href).searchParams.has(PARAM)) {
        window.history.replaceState(null, "", urlWith(wanted));
      } else {
        window.history.pushState(null, "", urlWith(wanted));
        pushed.current = true;
      }
    }
    // Capture, before Next's <Link> handles the click as a navigation.
    document.addEventListener("click", onClick, true);
    return () => document.removeEventListener("click", onClick, true);
  }, []);

  const close = useCallback(() => {
    if (pushed.current) {
      pushed.current = false;
      window.history.back();
    } else {
      window.history.replaceState(null, "", urlWith(null));
    }
  }, []);

  const reviewAll = useCallback(() => {
    window.history.replaceState(null, "", urlWith("all"));
  }, []);

  if (!mode) return null;
  // A new mode is a new sitting.
  return <ReviewDeck key={mode} mode={mode} onClose={close} onReviewAll={reviewAll} />;
}
