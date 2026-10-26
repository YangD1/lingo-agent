"use client";

import { type CSSProperties, type ReactNode, useEffect, useLayoutEffect, useMemo, useRef, useState, useTransition } from "react";

import {
  barrelMap,
  type Box,
  coverSide,
  hitBox,
  IDLE_AFTER,
  idleTarget,
  layoutWall,
  panFor,
  ROTATION,
  startOnMistake,
  toLocal,
  type WallRow,
  wheelStep,
} from "@/components/home/lens-math";
import { useReducedMotion } from "@/components/tutor/tutor-avatar";
import { setLocale } from "@/i18n/actions";

import s from "./landing.module.css";

const ZOOM = 1.6;
const WARP = 0.3;
const FILTER = "landing-barrel";

type Wall = { w: number; h: number; side: number; fontSize: number; radius: number; rows: WallRow[] };

function measureWall(hero: HTMLElement): Wall {
  const w = hero.clientWidth;
  const h = hero.clientHeight;
  // phones get smaller words and a smaller lens
  const small = w < 640;
  const fontSize = small ? 64 : 110;
  const side = coverSide(w, h);
  return { w, h, side, fontSize, radius: small ? 105 : 150, rows: layoutWall(side, fontSize) };
}

function WallWords({ rows }: { rows: WallRow[] }) {
  let i = 0;
  return rows.map((row, r) => (
    <div key={r} className={s.row} style={{ marginLeft: row.indent }}>
      {row.words.map(({ word, style }) => (
        <span key={i} data-i={i++} className={`${s.word} ${s[style]}`}>
          {word.word.replace(" ", " ")}
        </span>
      ))}
    </div>
  ));
}

/**
 * The first screen (ADR 0065 §1): a tilted wall of giant English words and a glass lens that
 * follows the pointer, magnifies the wall and shows what the tutor knows about the word under
 * it. The lens copies the wall and bends it with an SVG displacement filter. The wall is
 * decoration (`aria-hidden`); the copy on top comes in as `children`, rendered on the server.
 */
export function LensHero({
  meanings,
  hint,
  next,
  children,
}: {
  /** Meaning of each wall word by slug, in the page's language. */
  meanings: Record<string, string>;
  hint: string;
  next: string;
  children: ReactNode;
}) {
  const reduced = useReducedMotion();
  const hero = useRef<HTMLElement>(null);
  const wallEl = useRef<HTMLDivElement>(null);
  const inner = useRef<HTMLDivElement>(null);
  const lens = useRef<HTMLDivElement>(null);
  const content = useRef<HTMLDivElement>(null);
  const zoomWall = useRef<HTMLDivElement>(null);
  const zoomInner = useRef<HTMLDivElement>(null);
  const filter = useRef<SVGFilterElement>(null);
  const mapImage = useRef<SVGFEImageElement>(null);
  const displace = useRef<SVGFEDisplacementMapElement>(null);
  const [wall, setWall] = useState<Wall | null>(null);
  const [picked, setPicked] = useState(-1);
  // the motion lives outside React: it changes every frame
  const m = useRef({ x: 0, y: 0, tx: 0, ty: 0, px: 0, py: 0, wx: 0, wy: 0, lastMove: 0, boxes: [] as Box[] });
  const words = useMemo(() => wall?.rows.flatMap((row) => row.words.map(({ word }) => word)) ?? [], [wall]);

  // build the wall once the hero's size is known, again when it really changes (svh keeps it
  // steady while a phone's URL bar slides)
  useEffect(() => {
    const el = hero.current!;
    setWall(measureWall(el));
    let timer = 0;
    const onResize = () => {
      clearTimeout(timer);
      timer = window.setTimeout(() => {
        setWall((old) => (old && el.clientWidth === old.w && el.clientHeight === old.h ? old : measureWall(el)));
      }, 150);
    };
    addEventListener("resize", onResize);
    return () => {
      clearTimeout(timer);
      removeEventListener("resize", onResize);
    };
  }, []);

  useLayoutEffect(() => {
    if (!wall) return;
    const { w, h, side, radius } = wall;
    const state = m.current;
    const draw = () => {
      const t = `translate(-50%, -50%) translate(${state.px}px, ${state.py}px) rotate(${ROTATION}deg)`;
      inner.current!.style.transform = zoomInner.current!.style.transform = t;
      lens.current!.style.transform = `translate(${state.x - radius}px, ${state.y - radius}px)`;
      // wall point (x, y) stays under the lens centre; everything else scales around it
      zoomWall.current!.style.transform = `translate(${radius}px, ${radius}px) scale(${ZOOM}) translate(${-state.x}px, ${-state.y}px)`;
    };
    const pick = () => {
      const [lx, ly] = toLocal({ w, h, side, px: state.px, py: state.py }, state.x, state.y);
      setPicked(hitBox(state.boxes, lx, ly));
    };
    const measure = () => {
      state.boxes = Array.from(inner.current!.querySelectorAll<HTMLElement>("[data-i]"), (el) => ({
        l: el.offsetLeft,
        t: el.offsetTop,
        r: el.offsetLeft + el.offsetWidth,
        b: el.offsetTop + el.offsetHeight,
      }));
    };

    // the barrel map for this lens size
    const size = radius * 2;
    const n = 200;
    const canvas = document.createElement("canvas");
    canvas.width = canvas.height = n;
    const ctx = canvas.getContext("2d");
    if (ctx) {
      const image = ctx.createImageData(n, n);
      image.data.set(barrelMap(n));
      ctx.putImageData(image, 0, 0);
      mapImage.current!.setAttribute("href", canvas.toDataURL());
      for (const el of [filter.current!, mapImage.current!]) {
        el.setAttribute("width", String(size));
        el.setAttribute("height", String(size));
      }
      displace.current!.setAttribute("scale", (WARP * size).toFixed(1));
      content.current!.style.filter = `url(#${FILTER})`;
    }
    zoomWall.current!.style.width = `${w}px`;
    zoomWall.current!.style.height = `${h}px`;

    // start on a mistake near the upper middle, so a correction is the first thing seen
    const settle = () => {
      measure();
      const start = startOnMistake({ w, h, side }, state.boxes, (i) => words[i]?.ipa === null, radius, reduced);
      const fallback = { x: w * 0.58, y: h * 0.4, px: 0, py: 0, wx: 0, wy: 0 };
      if (!start && !reduced) [fallback.px, fallback.py] = panFor(w, h, fallback.x, fallback.y, 0, 0);
      Object.assign(state, start ?? fallback);
      state.tx = state.x;
      state.ty = state.y;
      state.lastMove = performance.now();
      draw();
      pick();
    };
    settle();
    const settledAt = state.lastMove;
    wallEl.current!.dataset.ready = "";
    lens.current!.dataset.ready = "";

    let cancelled = false;
    // the font changes every box's size
    document.fonts?.ready.then(() => {
      if (cancelled) return;
      // nobody has moved the lens yet: start it over on a mistake in the new layout
      if (state.lastMove === settledAt) settle();
      else {
        measure();
        pick();
      }
    });

    let heroOn = true;
    const seen = new IntersectionObserver(([e]) => (heroOn = e.isIntersecting));
    seen.observe(hero.current!);

    let raf = 0;
    const frame = (t: number) => {
      raf = requestAnimationFrame(frame);
      if (!heroOn) return;
      if (!reduced && t - state.lastMove > IDLE_AFTER) {
        [state.tx, state.ty] = idleTarget(w, h, (t - state.lastMove - IDLE_AFTER) / 1000);
      }
      const [gx, gy] = reduced ? [state.wx, state.wy] : panFor(w, h, state.tx, state.ty, state.wx, state.wy);
      // settled: skip the frame, since the lens filter re-runs on every draw
      if (Math.abs(state.tx - state.x) + Math.abs(state.ty - state.y) + Math.abs(gx - state.px) + Math.abs(gy - state.py) <= 0.05) return;
      const ease = reduced ? 1 : 0.16;
      state.x += (state.tx - state.x) * ease;
      state.y += (state.ty - state.y) * ease;
      state.px += (gx - state.px) * (reduced ? 1 : 0.08);
      state.py += (gy - state.py) * (reduced ? 1 : 0.08);
      draw();
      pick();
    };
    raf = requestAnimationFrame(frame);

    const el = hero.current!;
    const point = (e: PointerEvent) => {
      const b = el.getBoundingClientRect();
      state.tx = e.clientX - b.left;
      state.ty = e.clientY - b.top;
      state.lastMove = performance.now();
    };
    // browsers fire a zero-movement pointermove on load when the cursor rests on the page
    const onMove = (e: PointerEvent) => {
      if (e.movementX || e.movementY) point(e);
    };
    // a mouse leaving hands the lens back to the idle wander; a lifted finger keeps it put
    const onLeave = (e: PointerEvent) => {
      if (e.pointerType === "mouse") state.lastMove = performance.now() - IDLE_AFTER;
    };
    // the wheel drags the wall until it hits its edge; one more scroll down flips to screen two
    const onWheel = (e: WheelEvent) => {
      if (e.ctrlKey) return; // pinch-zoom
      const k = e.deltaMode === 1 ? 16 : e.deltaMode === 2 ? h : 1;
      let dx = e.deltaX * k;
      let dy = e.deltaY * k;
      if (e.shiftKey && !dx) [dx, dy] = [dy, 0];
      const step = wheelStep(state.wx, state.wy, dx, dy, w, h);
      if (!step.moved) {
        if (dy > 0 && el.getBoundingClientRect().top > -4) {
          e.preventDefault();
          goNext(reduced);
        }
        return;
      }
      state.wx = step.wx;
      state.wy = step.wy;
      e.preventDefault();
    };
    el.addEventListener("pointermove", onMove);
    el.addEventListener("pointerdown", point);
    el.addEventListener("pointerleave", onLeave);
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => {
      cancelled = true;
      cancelAnimationFrame(raf);
      seen.disconnect();
      el.removeEventListener("pointermove", onMove);
      el.removeEventListener("pointerdown", point);
      el.removeEventListener("pointerleave", onLeave);
      el.removeEventListener("wheel", onWheel);
    };
  }, [wall, words, reduced]);

  // ArrowDown / PageDown / Space on the first screen flip to the second, and the wheel is
  // swallowed while the flip runs, or a trackpad's momentum overshoots it
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.target as Element | null)?.closest?.("input, textarea, select, button, [contenteditable]")) return;
      if (["ArrowDown", "PageDown", " "].includes(e.key) && hero.current!.getBoundingClientRect().top > -4) {
        e.preventDefault();
        goNext(reduced);
      }
    };
    const onWheel = (e: WheelEvent) => {
      if (performance.now() < flipping) e.preventDefault();
    };
    addEventListener("keydown", onKey);
    addEventListener("wheel", onWheel, { passive: false });
    return () => {
      removeEventListener("keydown", onKey);
      removeEventListener("wheel", onWheel);
    };
  }, [reduced]);

  const word = picked >= 0 ? words[picked] : undefined;
  const mistake = word?.ipa === null || undefined;
  return (
    <section ref={hero} id="hero" className={s.hero} aria-labelledby="hero-title">
      <svg width="0" height="0" style={{ position: "absolute" }} aria-hidden>
        <filter
          ref={filter}
          id={FILTER}
          filterUnits="userSpaceOnUse"
          x="0"
          y="0"
          width="300"
          height="300"
          colorInterpolationFilters="sRGB"
        >
          <feImage ref={mapImage} x="0" y="0" width="300" height="300" preserveAspectRatio="none" result="map" />
          <feDisplacementMap
            ref={displace}
            in="SourceGraphic"
            in2="map"
            scale="90"
            xChannelSelector="R"
            yChannelSelector="G"
          />
        </filter>
      </svg>

      <div ref={wallEl} className={s.wall} aria-hidden data-testid="word-wall">
        <div
          ref={inner}
          className={s.wallInner}
          style={wall ? { width: wall.side, height: wall.side, fontSize: wall.fontSize } : undefined}
        >
          {wall && <WallWords rows={wall.rows} />}
        </div>
      </div>

      <div
        ref={lens}
        className={s.lens}
        aria-hidden
        data-testid="lens"
        style={{ "--r": `${wall?.radius ?? 150}px` } as CSSProperties}
      >
        <div className={s.lensShadow} />
        <div className={s.lensRim} />
        <div className={s.lensView}>
          <div ref={content} className={s.lensContent}>
            <div ref={zoomWall} className={s.wall}>
              <div
                ref={zoomInner}
                className={s.wallInner}
                style={wall ? { width: wall.side, height: wall.side, fontSize: wall.fontSize } : undefined}
              >
                {wall && <WallWords rows={wall.rows} />}
              </div>
            </div>
          </div>
          <div className={s.lensGlass} />
          <div className={s.lensWord} data-mistake={mistake}>
            {word && (word.ipa ? word.word : <s>{word.word}</s>)}
          </div>
          <div className={s.lensCap} data-mistake={mistake} data-testid="lens-caption">
            {word && (
              <>
                {word.ipa && <i>{word.ipa}</i>}
                {meanings[word.slug]}
                <b>{word.level}</b>
              </>
            )}
          </div>
        </div>
      </div>

      {children}

      <div className={`${s.hint} ${s.glassChip}`}>
        <span>{hint}</span>
        <kbd aria-hidden>↕</kbd>
      </div>
      <a
        className={`${s.next} ${s.glassChip}`}
        href="#more"
        onClick={(e) => {
          e.preventDefault();
          goNext(reduced);
        }}
      >
        <span>{next}</span>
        <span className={s.chev} aria-hidden>
          ⌄
        </span>
      </a>
    </section>
  );
}

// locked while the scroll runs, so a trackpad's momentum doesn't fire it twice
let flipping = 0;
function goNext(reduced: boolean) {
  if (performance.now() < flipping) return;
  const more = document.getElementById("more");
  if (!more) return;
  flipping = performance.now() + 900;
  more.scrollIntoView({ behavior: reduced ? "auto" : "smooth" });
  more.focus({ preventScroll: true });
}

/** One button naming the other language, in that language (ADR 0065 §5). */
export function LanguageButton({
  to,
  name,
  label,
  className,
}: {
  to: string;
  name: string;
  label: string;
  className?: string;
}) {
  const [pending, startTransition] = useTransition();
  return (
    <button
      type="button"
      className={className}
      lang={to}
      aria-label={label}
      disabled={pending}
      // the cookie is set in a Server Action, which re-renders the page in the new language
      onClick={() => startTransition(() => setLocale(to))}
    >
      {name}
    </button>
  );
}
