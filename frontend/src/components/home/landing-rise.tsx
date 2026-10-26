"use client";

import { type ReactNode, useEffect, useRef } from "react";

/**
 * Fades in each `[data-rise]` inside it the first time it enters the viewport (ADR 0065 §3). The
 * CSS only hides them once this has armed the container, so without JS everything is visible;
 * reduced motion turns the fade off in CSS.
 */
export function RiseIn({ className, children }: { className?: string; children: ReactNode }) {
  const root = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = root.current!;
    const io = new IntersectionObserver((entries) => {
      for (const e of entries) {
        if (!e.isIntersecting) continue;
        e.target.setAttribute("data-in", "");
        io.unobserve(e.target);
      }
    });
    el.querySelectorAll("[data-rise]").forEach((x) => io.observe(x));
    el.setAttribute("data-armed", "");
    return () => io.disconnect();
  }, []);

  return (
    <div ref={root} className={className}>
      {children}
    </div>
  );
}
