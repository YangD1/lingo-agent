"use client";

import {
  ArrowRightIcon,
  BookOpenIcon,
  CheckIcon,
  ChevronRightIcon,
  DumbbellIcon,
  LayersIcon,
  LoaderCircleIcon,
} from "lucide-react";
import { type ReactNode, type RefObject, useEffect, useRef, useState } from "react";

import { LogoMark } from "@/components/brand/logo";
import { useReducedMotion } from "@/components/home/landing-backdrop";
import { cn } from "@/lib/utils";

/**
 * The home page's example conversations, each played as a turn in the real chat goes: the tutor
 * reads its memories, streams the reply, calls a tool mid-reply, then works in the background.
 * The topics take turns, and the tabs jump to one. Every topic sits in the same grid cell and
 * every part keeps its final place from the start (only its opacity changes), so the card stays
 * as tall as the tallest topic. It pauses off screen and shows a finished turn at once under
 * reduced motion. The motion is decoration: screen readers get the text.
 */

type Step = {
  name: string;
  running: string;
  done: string;
  detail?: string;
  fix?: { wrong: string; right: string; rule: string };
};

export type ChatDemoScene = {
  topic: string;
  user: string;
  contextDone: string;
  memory: string;
  /** May mark phrases as `<b>…</b>`, as may `summary`. */
  reply: string;
  tool: Step & { card: string; action: string; icon: "practice" | "review" | "book" };
  note: string;
  after: Step[];
  summary: string;
};

export type ChatDemoCopy = {
  label: string;
  topics: string;
  stepContext: string;
  activity: string;
  scenes: ChatDemoScene[];
};

type Token = { text: string; bold: boolean };

/* A CJK character streams on its own; anything else streams a word with its trailing space. */
const TOKEN = /[　-〿㐀-鿿＀-￯]|[^\s　-〿㐀-鿿＀-￯]+\s*|\s+/g;

export function tokenize(text: string): Token[] {
  return text
    .split(/(<b>.*?<\/b>)/)
    .flatMap((part) => {
      const bold = part.startsWith("<b>");
      const plain = bold ? part.slice(3, -4) : part;
      return (plain.match(TOKEN) ?? []).map((t) => ({ text: t, bold }));
    });
}

const plain = (text: string) => text.replace(/<\/?b>/g, "");

const TOKEN_MS = 45;
const HOLD_MS = 3000;
const FADE_MS = 400;
const TICK_MS = 50;

/** When each part starts and finishes, in ms from the start of the turn. */
export function schedule(replyTokens: number, noteTokens: number, afterSteps: number) {
  const context = { start: 400, done: 1200 };
  const reply = { start: 1400, done: 1400 + replyTokens * TOKEN_MS };
  const tool = { start: reply.done + 200, done: reply.done + 1200 };
  const note = { start: tool.done + 350, done: tool.done + 350 + noteTokens * TOKEN_MS };
  const after = Array.from({ length: afterSteps }, (_, i) => ({
    start: note.done + 350 + i * 250,
    done: note.done + 1150 + i * 500,
  }));
  const summary = (after.at(-1)?.done ?? note.done) + 250;
  return { context, reply, tool, note, after, summary, end: summary + HOLD_MS };
}

type Span = { start: number; done: number };
type Phase = "idle" | "run" | "done";
const phaseAt = (ms: number, span: Span): Phase =>
  ms < span.start ? "idle" : ms < span.done ? "run" : "done";

type Clock = { scene: number; ms: number };

/** The playing topic and how far into it, moving on to the next topic at each end. */
function useClock(ends: number[], root: RefObject<HTMLElement | null>) {
  const still = useReducedMotion();
  const [clock, setClock] = useState<Clock>({ scene: 0, ms: 0 });
  const endsKey = ends.join();
  useEffect(() => {
    if (still) return;
    const element = root.current;
    const limits = endsKey.split(",").map(Number);
    let inView = false;
    let timer: ReturnType<typeof setInterval> | undefined;
    const tick = () =>
      setClock(({ scene, ms }) =>
        ms + TICK_MS >= (limits[scene] ?? 0)
          ? { scene: (scene + 1) % limits.length, ms: 0 }
          : { scene, ms: ms + TICK_MS },
      );
    const sync = () => {
      const run = inView && document.visibilityState === "visible";
      if (run && !timer) {
        timer = setInterval(tick, TICK_MS);
      } else if (!run && timer) {
        clearInterval(timer);
        timer = undefined;
      }
    };
    const observer = new IntersectionObserver(([entry]) => {
      inView = entry?.isIntersecting ?? false;
      sync();
    });
    if (element) observer.observe(element);
    document.addEventListener("visibilitychange", sync);
    return () => {
      observer.disconnect();
      document.removeEventListener("visibilitychange", sync);
      if (timer) clearInterval(timer);
    };
  }, [still, endsKey, root]);
  const pick = (scene: number) => setClock({ scene, ms: 0 });
  const ms = still ? (ends[clock.scene] ?? 0) - FADE_MS - TICK_MS : clock.ms;
  return { scene: clock.scene, ms, pick };
}

function Streamed({ tokens, shown, streaming }: { tokens: Token[]; shown: number; streaming: boolean }) {
  return (
    <>
      {tokens.map((token, i) => {
        const Tag = token.bold ? "strong" : "span";
        return (
          <Tag key={i} className={cn(i >= shown && "text-transparent")}>
            {token.text}
            {streaming && i === shown - 1 && (
              <span className="ml-0.5 inline-block h-[1.05em] w-[2px] translate-y-[3px] animate-pulse rounded-full bg-brand align-baseline" />
            )}
          </Tag>
        );
      })}
    </>
  );
}

function StepLine({
  phase,
  name,
  running,
  done,
  children,
}: {
  phase: Phase;
  name: string;
  running: string;
  done: string;
  children?: ReactNode;
}) {
  return (
    <div
      className={cn(
        "flex flex-col gap-1 text-[12.5px] text-muted-foreground transition-opacity duration-300",
        phase === "idle" ? "opacity-0" : "opacity-100",
      )}
    >
      <p className="flex items-center gap-1.5">
        {phase === "done" ? (
          <CheckIcon className="size-3.5 shrink-0 text-success" />
        ) : (
          <LoaderCircleIcon className="size-3.5 shrink-0 animate-spin text-ai" />
        )}
        <code className="rounded bg-ai/10 px-1.5 py-px font-mono text-[11px] text-ai">{name}</code>
        <span className={cn(phase === "done" && "text-foreground/75")}>
          {phase === "done" ? done : running}
        </span>
      </p>
      {children && (
        <div
          className={cn(
            "pl-5 transition-opacity duration-300",
            phase === "done" ? "opacity-100" : "opacity-0",
          )}
        >
          {children}
        </div>
      )}
    </div>
  );
}

const ICONS = { practice: DumbbellIcon, review: LayersIcon, book: BookOpenIcon };

function Scene({
  scene,
  ms,
  active,
  stepContext,
  activity,
}: {
  scene: ChatDemoScene;
  ms: number;
  active: boolean;
  stepContext: string;
  activity: string;
}) {
  const reply = tokenize(scene.reply);
  const note = tokenize(scene.note);
  const plan = schedule(reply.length, note.length, scene.after.length);
  const shown = (span: Span, count: number) =>
    Math.max(0, Math.min(count, Math.ceil((ms - span.start) / TOKEN_MS)));
  const tool = phaseAt(ms, plan.tool);
  const fading = ms > plan.end - FADE_MS;
  const Icon = ICONS[scene.tool.icon];

  return (
    <div
      className={cn(
        "col-start-1 row-start-1 flex flex-col gap-4 transition-opacity",
        !active && "invisible opacity-0",
        active && (fading ? "opacity-0 duration-[400ms]" : "opacity-100 duration-200"),
      )}
    >
      <p className="max-w-[86%] self-end rounded-[18px_18px_6px_18px] bg-primary px-[15px] py-2.5 text-[15px] leading-[1.6] text-primary-foreground">
        {scene.user}
      </p>
      <div className="relative flex flex-col gap-2.5 md:pl-[42px]">
        <span className="absolute top-0 left-0 hidden size-[30px] items-center justify-center rounded-full bg-brand-soft md:flex">
          <LogoMark className="size-5" />
        </span>
        <StepLine
          phase={phaseAt(ms, plan.context)}
          name="load_context"
          running={stepContext}
          done={scene.contextDone}
        >
          <p className="text-[12.5px]">{scene.memory}</p>
        </StepLine>

        <div
          className={cn(
            "flex flex-col gap-2.5 rounded-[6px_18px_18px_18px] border px-3.5 py-3 text-[14.5px] leading-[1.7] transition-opacity duration-300",
            ms >= plan.reply.start ? "opacity-100" : "opacity-0",
          )}
        >
          <p>
            <Streamed
              tokens={reply}
              shown={shown(plan.reply, reply.length)}
              streaming={phaseAt(ms, plan.reply) === "run"}
            />
          </p>
          <StepLine phase={tool} name={scene.tool.name} running={scene.tool.running} done={scene.tool.done} />
          <div
            className={cn(
              "flex items-center gap-3 rounded-xl border bg-background/70 px-3 py-2.5 transition-all duration-500",
              tool === "done" ? "translate-y-0 opacity-100" : "translate-y-1 opacity-0",
            )}
          >
            <span className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-brand-soft text-brand">
              <Icon className="size-4" />
            </span>
            <span className="min-w-0 flex-1 text-[13.5px] leading-snug font-medium">{scene.tool.card}</span>
            <span className="inline-flex h-7 shrink-0 items-center gap-1 rounded-full bg-primary px-3 text-xs font-medium text-primary-foreground">
              {scene.tool.action}
              <ArrowRightIcon className="size-3" />
            </span>
          </div>
          <p>
            <Streamed
              tokens={note}
              shown={shown(plan.note, note.length)}
              streaming={phaseAt(ms, plan.note) === "run"}
            />
          </p>
        </div>

        {scene.after.map((step, i) => (
          <StepLine
            key={step.name}
            phase={phaseAt(ms, plan.after[i] ?? plan.note)}
            name={step.name}
            running={step.running}
            done={step.done}
          >
            {step.fix ? (
              <p className="flex flex-wrap items-center gap-x-2 text-[12.5px]">
                <s>{step.fix.wrong}</s>
                <span>→</span>
                <span className="text-success">{step.fix.right}</span>
                <span className="text-primary">· {step.fix.rule}</span>
              </p>
            ) : (
              <p className="text-[12.5px]">{step.detail}</p>
            )}
          </StepLine>
        ))}

        <p
          className={cn(
            "flex w-fit items-center gap-1 rounded-full border border-border/70 bg-card/70 py-1 pr-2.5 pl-1.5 text-xs text-foreground/75 transition-opacity duration-500",
            ms >= plan.summary ? "opacity-100" : "opacity-0",
          )}
        >
          <ChevronRightIcon className="size-3.5 shrink-0" />
          <span>
            {activity}{" "}
            {scene.summary.split(/(<b>.*?<\/b>)/).map((part, i) =>
              part.startsWith("<b>") ? (
                <strong key={i} className="text-foreground">
                  {plain(part)}
                </strong>
              ) : (
                part
              ),
            )}
          </span>
        </p>
      </div>
    </div>
  );
}

export function ChatDemo({ copy, className }: { copy: ChatDemoCopy; className?: string }) {
  const root = useRef<HTMLElement>(null);
  const ends = copy.scenes.map(
    (s) => schedule(tokenize(s.reply).length, tokenize(s.note).length, s.after.length).end,
  );
  const { scene: current, ms, pick } = useClock(ends, root);
  const playing = copy.scenes[current];

  return (
    <figure
      ref={root}
      aria-label={copy.label}
      className={cn(
        "flex flex-col gap-4 rounded-2xl border bg-card p-4 shadow-[var(--shadow-lift)] md:p-5",
        className,
      )}
    >
      <div role="group" aria-label={copy.topics} className="flex flex-wrap gap-1.5">
        {copy.scenes.map((scene, i) => (
          <button
            key={scene.topic}
            type="button"
            aria-pressed={i === current}
            onClick={() => pick(i)}
            className={cn(
              "rounded-full px-3 py-1 text-xs font-medium transition-colors",
              i === current
                ? "bg-foreground text-background"
                : "bg-muted text-muted-foreground hover:text-foreground",
            )}
          >
            {scene.topic}
          </button>
        ))}
      </div>
      {playing && (
        <figcaption className="sr-only">
          {playing.user} {plain(playing.reply)} {playing.note}
        </figcaption>
      )}
      <div aria-hidden className="grid">
        {copy.scenes.map((scene, i) => (
          <Scene
            key={scene.topic}
            scene={scene}
            ms={i === current ? ms : 0}
            active={i === current}
            stepContext={copy.stepContext}
            activity={copy.activity}
          />
        ))}
      </div>
    </figure>
  );
}
