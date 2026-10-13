"use client";

import { ChevronDownIcon } from "lucide-react";
import { useTranslations } from "next-intl";
import { useRef, useState, useSyncExternalStore } from "react";

import { type PetPlace, usePetPlace } from "@/lib/preferences";
import { useTutor } from "@/lib/tutor";
import { cn } from "@/lib/utils";

import { TutorAvatar } from "./tutor-avatar";

/** A press that moves less than this is a tap, not a drag. */
export const DRAG_THRESHOLD_PX = 5;
/** Space kept between the pet and the window's edges. */
const EDGE_PX = 12;

const PET_SIZE = { wide: 88, narrow: 64 };
const COLLAPSED_SIZE = 40;

const WIDE = "(min-width: 768px)";

function useWide(): boolean {
  return useSyncExternalStore(
    (listener) => {
      const query = window.matchMedia?.(WIDE);
      query?.addEventListener("change", listener);
      return () => query?.removeEventListener("change", listener);
    },
    () => window.matchMedia?.(WIDE).matches ?? true,
    () => true,
  );
}

/** Where a pet dropped with its box at `rect` settles: the nearer edge, at that height. */
export function placeAfterDrop(
  rect: { left: number; top: number; width: number; height: number },
  viewport: { width: number; height: number },
  collapsed: boolean,
): PetPlace {
  const center = rect.left + rect.width / 2;
  return {
    side: center < viewport.width / 2 ? "left" : "right",
    bottom: Math.max(0, Math.round(viewport.height - rect.top - rect.height)),
    collapsed,
  };
}

type Drag = {
  pointer: number;
  startX: number;
  startY: number;
  rect: DOMRect;
  /** Where the box is while moving; null until it has moved past the threshold. */
  at: { left: number; top: number } | null;
};

/**
 * The learner's tutor as a desk pet (ADR 0032 §4a): floating in a corner of every page,
 * draggable to either edge, collapsible to a small button. Where it sits is kept on this
 * device; whether it shows is the learner's tutor setting. Smaller on phones, and above
 * the tab bar there.
 */
export function TutorPet() {
  const tutor = useTutor();
  const [place, setPlace] = usePetPlace();
  const wide = useWide();
  const t = useTranslations("tutorPet");
  const box = useRef<HTMLDivElement>(null);
  const [drag, setDrag] = useState<Drag | null>(null);
  // A drag ends with a click on what was pressed: that click is not a tap.
  const dragged = useRef(false);

  if (!tutor?.pet) return null;
  const name = tutor.display_name;
  const size = place.collapsed ? COLLAPSED_SIZE : wide ? PET_SIZE.wide : PET_SIZE.narrow;

  const onPointerDown = (e: React.PointerEvent) => {
    if (e.button !== 0 || !box.current) return;
    dragged.current = false;
    setDrag({
      pointer: e.pointerId,
      startX: e.clientX,
      startY: e.clientY,
      rect: box.current.getBoundingClientRect(),
      at: null,
    });
  };
  const onPointerMove = (e: React.PointerEvent) => {
    if (!drag || e.pointerId !== drag.pointer) return;
    const dx = e.clientX - drag.startX;
    const dy = e.clientY - drag.startY;
    if (!drag.at && Math.hypot(dx, dy) < DRAG_THRESHOLD_PX) return;
    // Captured only once it is a drag: capturing on press would take a tap's click away
    // from the button pressed.
    if (!drag.at) box.current?.setPointerCapture?.(e.pointerId);
    const { rect } = drag;
    setDrag({
      ...drag,
      at: {
        left: clamp(rect.left + dx, 0, window.innerWidth - rect.width),
        top: clamp(rect.top + dy, 0, window.innerHeight - rect.height),
      },
    });
  };
  const onPointerUp = (e: React.PointerEvent) => {
    if (!drag || e.pointerId !== drag.pointer) return;
    setDrag(null);
    if (!drag.at) return;
    dragged.current = true;
    setPlace(
      placeAfterDrop(
        { ...drag.at, width: drag.rect.width, height: drag.rect.height },
        { width: window.innerWidth, height: window.innerHeight },
        place.collapsed,
      ),
    );
  };
  const notAfterDrag = (e: React.MouseEvent) => {
    if (!dragged.current) return;
    dragged.current = false;
    e.preventDefault();
    e.stopPropagation();
  };

  const moving = drag?.at ?? null;
  // Kept on screen whatever the window's size: above the phone's tab bar, below the top.
  const style: React.CSSProperties = moving
    ? { left: moving.left, top: moving.top }
    : {
        [place.side]: place.collapsed ? 0 : EDGE_PX,
        bottom: `min(max(${place.bottom}px, var(--pet-min-bottom)), calc(100dvh - ${size + EDGE_PX}px))`,
      };

  return (
    <div
      ref={box}
      data-testid="tutor-pet"
      data-side={place.side}
      data-collapsed={place.collapsed || undefined}
      style={style}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
      onPointerCancel={() => setDrag(null)}
      onClickCapture={notAfterDrag}
      className={cn(
        "group fixed z-40 touch-none select-none",
        "[--pet-min-bottom:16px] max-md:[--pet-min-bottom:calc(4rem+env(safe-area-inset-bottom)+8px)]",
        moving ? "cursor-grabbing" : "cursor-grab",
      )}
    >
      {place.collapsed ? (
        <button
          type="button"
          aria-label={t("expand", { name })}
          title={t("expand", { name })}
          onClick={() => setPlace({ ...place, collapsed: false })}
          className={cn(
            "flex items-center justify-center border bg-card shadow-md outline-none focus-visible:ring-3 focus-visible:ring-ring/50",
            place.side === "right" ? "rounded-l-full border-r-0" : "rounded-r-full border-l-0",
          )}
          style={{ width: size, height: size }}
        >
          <TutorAvatar
            outfit={tutor.display_avatar}
            fur={tutor.color}
            animate={false}
            size={size - 8}
            label=""
          />
        </button>
      ) : (
        <>
          <TutorAvatar
            outfit={tutor.display_avatar}
            fur={tutor.color}
            animate={tutor.animate}
            size={size}
            label={t("label", { name })}
            className="drop-shadow-md"
          />
          <button
            type="button"
            aria-label={t("collapse")}
            title={t("collapse")}
            onClick={() => setPlace({ ...place, collapsed: true })}
            className={cn(
              "absolute -top-1 flex size-6 items-center justify-center rounded-full border bg-card text-muted-foreground shadow-sm outline-none hover:text-foreground focus-visible:opacity-100 focus-visible:ring-3 focus-visible:ring-ring/50 [&_svg]:size-3.5",
              place.side === "right" ? "-left-1" : "-right-1",
              // Hover shows it with a mouse; on touch screens it is always there.
              "md:opacity-0 md:group-hover:opacity-100",
            )}
          >
            <ChevronDownIcon aria-hidden />
          </button>
        </>
      )}
    </div>
  );
}

function clamp(value: number, low: number, high: number): number {
  return Math.min(Math.max(value, low), Math.max(low, high));
}
