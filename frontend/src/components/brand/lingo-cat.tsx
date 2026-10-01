"use client";

import { useTranslations } from "next-intl";
import { useEffect, useState, type ReactNode } from "react";

import { cn } from "@/lib/utils";

/**
 * The logo cat in six moods (docs/design/lingo-cat-motion, styles in lingo-cat.css):
 * loader / hop / ai loop; done and oops play once and stop (remount with a new `key` to
 * replay); idle is a slow loop for empty states. At size ≤ 24 only the tail and the spark
 * move. Reduced motion is handled in the stylesheet.
 */
export type LingoCatMood = "loader" | "hop" | "ai" | "done" | "idle" | "oops";

const SPARK = "M43 12.5Q43 19 49.5 19Q43 19 43 25.5Q43 19 36.5 19Q43 19 43 12.5Z";

export function LingoCat({
  mood = "loader",
  size = 96,
  small,
  label,
  className,
}: {
  mood?: LingoCatMood;
  size?: number;
  small?: boolean;
  /** Accessible name; defaults to the mood's own. Pass "" to hide the cat from assistive tech. */
  label?: string;
  className?: string;
}) {
  const t = useTranslations("cat");
  const text = label ?? (mood === "idle" ? "" : t(mood));
  return (
    <svg
      viewBox="0 0 64 64"
      width={size}
      height={size}
      role={text ? "img" : undefined}
      aria-label={text || undefined}
      aria-hidden={text ? undefined : true}
      data-mood={mood}
      className={cn(
        "lcat shrink-0",
        mood !== "loader" && `v-${mood}`,
        (small ?? size <= 24) && "sm",
        className,
      )}
    >
      <ellipse className="shadow" cx="30" cy="55.6" rx="22" ry="1.6" />
      <g className="catg">
        <path className="tail" d="M31 51.2H42" />
        <g className="tailg">
          <path className="tail" d="M42 51.2C49 51.2 52.5 46.4 51.5 41.2" />
          <g className="tipg">
            <path className="tail" d="M51.5 41.2C50.6 36.8 45.6 35.8 43 38.8" />
          </g>
        </g>
        <g className="bodyg">
          <path
            className="body"
            stroke="none"
            d="M15 23C8.8 30 8.2 43.6 9.6 50.2Q10.4 54 14.6 54H29.4Q33.6 54 34.4 50.2C35.8 43.6 35.2 30 29 23Z"
          />
          <g className="headg">
            <g className="earL">
              <path className="head" strokeWidth="3.4" d="M14.4 14.4L12.8 5.4L18 10.8Z" />
            </g>
            <g className="earR">
              <path className="head" strokeWidth="3.4" d="M29.6 14.4L31.2 5.4L26 10.8Z" />
            </g>
            <ellipse className="head" stroke="none" cx="22" cy="19.2" rx="10.8" ry="10.4" />
          </g>
        </g>
      </g>
      <path className="spark s2" d={SPARK} />
      <path className="spark s3" d={SPARK} />
      <path className="spark s1" d={SPARK} />
    </svg>
  );
}

/** Renders `children` only once `ms` have passed, so quick waits don't flash a loader. */
export function Delayed({ ms = 300, children }: { ms?: number; children: ReactNode }) {
  const [shown, setShown] = useState(false);
  useEffect(() => {
    const id = setTimeout(() => setShown(true), ms);
    return () => clearTimeout(id);
  }, [ms]);
  return shown ? children : null;
}

/** A centred loader cat with its label underneath, shown after 300ms. Replaces bare “Loading…” text. */
export function CatLoading({
  label,
  mood = "loader",
  size = 56,
  className,
}: {
  label: string;
  mood?: "loader" | "hop" | "ai";
  size?: number;
  className?: string;
}) {
  return (
    <div
      role="status"
      aria-label={label}
      className={cn("flex flex-col items-center justify-center gap-2 py-6 text-sm text-muted-foreground", className)}
    >
      <Delayed>
        <LingoCat mood={mood} size={size} label="" />
        <span aria-hidden>{label}</span>
      </Delayed>
    </div>
  );
}
