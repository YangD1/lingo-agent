"use client";

import { useEffect, useRef, useState } from "react";

import { type DemoCopy, SCENES } from "@/components/home/demo-copy";
import type { Player } from "@/components/home/demo-player";
import { useReducedMotion } from "@/components/tutor/tutor-avatar";

import c from "./landing-demo.module.css";

/**
 * Screen two (ADR 0065 §2): a chat window playing example turns, with tabs to jump to one.
 * Until the section is within a screen of the viewport it is an empty frame; then the player
 * (demo-player.ts, its own chunk) is imported and builds the window. It plays only while at
 * least a third of the window is on screen and the tab is visible. Screen readers get the
 * scene's name; the window itself is decoration.
 */
export function DemoSection({ copy }: { copy: DemoCopy }) {
  const reduced = useReducedMotion();
  const section = useRef<HTMLElement>(null);
  const win = useRef<HTMLDivElement>(null);
  const player = useRef<Player | null>(null);
  const [near, setNear] = useState(false);
  const [built, setBuilt] = useState(false);
  const [scene, setScene] = useState(0);
  // a language switch rebuilds the window on the scene it was showing
  const current = useRef(0);

  useEffect(() => {
    const io = new IntersectionObserver(
      ([e]) => {
        if (!e.isIntersecting) return;
        io.disconnect();
        setNear(true);
      },
      { rootMargin: "100% 0px" },
    );
    io.observe(section.current!);
    return () => io.disconnect();
  }, []);

  useEffect(() => {
    if (!near) return;
    let cancelled = false;
    let inView = false;
    let p: Player | undefined;
    const sync = () => p?.setPlaying(inView && document.visibilityState === "visible");
    const seen = new IntersectionObserver(
      ([e]) => {
        inView = e.isIntersecting;
        sync();
      },
      { threshold: 0.35 },
    );
    void import("@/components/home/demo-player").then(({ createPlayer }) => {
      if (cancelled) return;
      const onScene = (i: number) => {
        current.current = i;
        setScene(i);
      };
      p = createPlayer(win.current!, copy, { reduced, onScene });
      player.current = p;
      seen.observe(win.current!);
      document.addEventListener("visibilitychange", sync);
      p.play(current.current);
      setBuilt(true);
    });
    return () => {
      cancelled = true;
      seen.disconnect();
      document.removeEventListener("visibilitychange", sync);
      p?.destroy();
      player.current = null;
    };
  }, [near, copy, reduced]);

  return (
    <section ref={section} id="more" tabIndex={-1} className={c.demo} aria-labelledby="demo-title">
      <header className={c.head}>
        <div>
          <span className={c.kicker}>{copy.kicker}</span>
          <h2 id="demo-title">{copy.title}</h2>
        </div>
        <div className={c.tabs} role="group" aria-label={copy.tabsLabel}>
          {SCENES.map((key, i) => (
            <button
              key={key}
              type="button"
              aria-pressed={i === scene}
              onClick={() => {
                current.current = i;
                setScene(i);
                player.current?.play(i);
              }}
            >
              {copy.tabs[key]}
            </button>
          ))}
        </div>
      </header>
      <div ref={win} className={c.win} aria-hidden data-testid="demo-window" data-built={built || undefined} />
      <p className="sr-only" aria-live="polite">
        {built ? copy.tabs[SCENES[scene]] : ""}
      </p>
    </section>
  );
}
