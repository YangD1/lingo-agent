"use client";

import { useEffect, useRef, useSyncExternalStore } from "react";

import { cn } from "@/lib/utils";
import { voiceLevel, watchLevel } from "@/lib/voice-level";

import { drawAvatar, OUTFITS, paletteFor, type Outfit } from "./avatar-draw";
import { createAnimator, stillPose, type AvatarState } from "./avatar-state";

/**
 * The learner's tutor, a cat in an outfit (ADR 0032 §4), drawn on a canvas at the screen's
 * pixel density. It blinks and breathes, leans in to listen, looks up to think, moves its
 * mouth with the tutor's voice (`voice-level`) and hops when glad. With reduced motion, or
 * the learner's animation off, it is drawn once and still; it stops drawing while the page
 * is hidden.
 */
export function TutorAvatar({
  outfit,
  fur,
  state = "idle",
  size = 96,
  animate = true,
  label,
  className,
}: {
  /** An outfit id; an unknown one (from a newer backend) draws the plain cat. */
  outfit?: string | null;
  /** The fur, `#rrggbb`; null: the logo orange. */
  fur?: string | null;
  state?: AvatarState;
  /** CSS pixels, square. */
  size?: number;
  /** The learner's animation switch. */
  animate?: boolean;
  /** Accessible name; "" hides it from assistive tech. */
  label: string;
  className?: string;
}) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const reduced = useReducedMotion();
  const moving = animate && !reduced;
  const visible = usePageVisible();
  const look = {
    outfit: (OUTFITS as readonly string[]).includes(outfit ?? "") ? (outfit as Outfit) : "cat",
    palette: paletteFor(fur),
    small: size < 48,
  };
  // The loop reads the latest props without restarting.
  const latest = useRef({ look, state });
  useEffect(() => {
    latest.current = { look, state };
  });

  // Still: one frame whenever something drawn changes.
  const { outfit: shownOutfit, palette, small } = look;
  useEffect(() => {
    if (moving) return;
    const ctx = prepare(canvas.current, size);
    if (!ctx) return;
    drawAvatar(ctx, stillPose(state), {
      outfit: shownOutfit,
      palette,
      small,
      ink: inkOf(canvas.current!),
      speakerMark: state === "speaking",
    });
    // `palette` is rebuilt each render; its fur is what matters.
  }, [moving, size, shownOutfit, palette.fur, small, state]); // eslint-disable-line react-hooks/exhaustive-deps

  // Moving: a frame each display refresh while the page is visible.
  useEffect(() => {
    if (!moving || !visible) return;
    const element = canvas.current;
    if (!element) return;
    const animator = createAnimator();
    const stopWatching = watchLevel();
    let ink = inkOf(element);
    let inkAt = 0;
    let frame = 0;
    const draw = (now: number) => {
      frame = requestAnimationFrame(draw);
      const ctx = prepare(element, size);
      if (!ctx) return;
      // The theme can change under it; the text color is read again once a second.
      if (now - inkAt > 1000) {
        ink = inkOf(element);
        inkAt = now;
      }
      const { look, state } = latest.current;
      const pose = animator.step(now, state, state === "speaking" ? voiceLevel(now) : 0);
      drawAvatar(ctx, pose, { ...look, ink, speakerMark: false });
    };
    frame = requestAnimationFrame(draw);
    return () => {
      cancelAnimationFrame(frame);
      stopWatching();
    };
  }, [moving, visible, size]);

  return (
    <canvas
      ref={canvas}
      width={size}
      height={size}
      style={{ width: size, height: size }}
      role={label ? "img" : undefined}
      aria-label={label || undefined}
      aria-hidden={label ? undefined : true}
      data-state={state}
      data-outfit={look.outfit}
      data-animated={moving ? "" : undefined}
      className={cn("shrink-0", className)}
    />
  );
}

/**
 * Sizes `element`'s backing store to `size` CSS pixels at the current pixel density (which
 * changes when the window moves to another screen or zooms), and scales its context to the
 * avatar's 100×100 box. Null where there is no 2D canvas.
 */
export function prepare(element: HTMLCanvasElement | null, size: number) {
  if (!element) return null;
  const ratio = typeof window === "undefined" ? 1 : window.devicePixelRatio || 1;
  const pixels = Math.round(size * ratio);
  if (element.width !== pixels || element.height !== pixels) {
    element.width = element.height = pixels;
  }
  const ctx = element.getContext("2d");
  if (!ctx) return null;
  ctx.setTransform(pixels / 100, 0, 0, pixels / 100, 0, 0);
  return ctx;
}

const inkOf = (element: HTMLElement) => getComputedStyle(element).color || "#6b7280";

const REDUCED = "(prefers-reduced-motion: reduce)";

/** Whether the system asks for less motion. */
export function useReducedMotion(): boolean {
  return useSyncExternalStore(
    (listener) => {
      const query = window.matchMedia?.(REDUCED);
      query?.addEventListener?.("change", listener);
      return () => query?.removeEventListener?.("change", listener);
    },
    () => window.matchMedia?.(REDUCED).matches ?? false,
    () => true, // the server draws nothing moving
  );
}

function usePageVisible(): boolean {
  return useSyncExternalStore(
    (listener) => {
      document.addEventListener("visibilitychange", listener);
      return () => document.removeEventListener("visibilitychange", listener);
    },
    () => document.visibilityState !== "hidden",
    () => false,
  );
}
