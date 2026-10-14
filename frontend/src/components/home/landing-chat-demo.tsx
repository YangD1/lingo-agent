"use client";

import { ArrowRightIcon, CheckIcon, ChevronRightIcon, DumbbellIcon, LoaderCircleIcon } from "lucide-react";
import { type ReactNode, type RefObject, useEffect, useRef, useState } from "react";

import { LogoMark } from "@/components/brand/logo";
import { useReducedMotion } from "@/components/home/landing-backdrop";
import { cn } from "@/lib/utils";

/**
 * The home page's example conversation, played as a turn in the real chat goes: the tutor reads
 * its memories, streams the reply, calls a tool mid-reply, then tags grammar and saves a memory
 * in the background. Every part keeps its final place from the start (only its opacity
 * changes), so the card never changes height. It pauses off screen, loops, and shows the end
 * state at once under reduced motion. The motion is decoration: screen readers get the text.
 */

export type ChatDemoCopy = {
  label: string;
  user: string;
  /** May mark one phrase as `<b>…</b>`. */
  reply: string;
  replyNote: string;
  stepContext: string;
  stepContextDone: string;
  memory: string;
  stepTool: string;
  stepToolDone: string;
  practiceCard: string;
  practiceStart: string;
  stepGrammar: string;
  stepGrammarDone: string;
  stepMemory: string;
  stepMemoryDone: string;
  memorySaved: string;
  wrong: string;
  right: string;
  rule: string;
  activity: string;
  activityRead: string;
  activityRest: string;
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

const TOKEN_MS = 55;
const HOLD_MS = 4500;
const FADE_MS = 500;
const TICK_MS = 50;

/** When each part starts and finishes, in ms from the start of the loop. */
export function schedule(replyTokens: number, noteTokens: number) {
  const context = { start: 500, done: 1400 };
  const reply = { start: 1600, done: 1600 + replyTokens * TOKEN_MS };
  const tool = { start: reply.done + 250, done: reply.done + 1350 };
  const note = { start: tool.done + 400, done: tool.done + 400 + noteTokens * TOKEN_MS };
  const grammar = { start: note.done + 400, done: note.done + 1200 };
  const memory = { start: note.done + 600, done: note.done + 1900 };
  const summary = memory.done + 250;
  return { context, reply, tool, note, grammar, memory, summary, end: summary + HOLD_MS };
}

type Span = { start: number; done: number };
type Phase = "idle" | "run" | "done";
const phaseAt = (ms: number, span: Span): Phase =>
  ms < span.start ? "idle" : ms < span.done ? "run" : "done";

function useLoopClock(end: number, root: RefObject<HTMLElement | null>): number {
  const still = useReducedMotion();
  const [ms, setMs] = useState(0);
  useEffect(() => {
    if (still) return;
    const element = root.current;
    let inView = false;
    let timer: ReturnType<typeof setInterval> | undefined;
    const sync = () => {
      const run = inView && document.visibilityState === "visible";
      if (run && !timer) {
        timer = setInterval(() => setMs((m) => (m + TICK_MS >= end ? 0 : m + TICK_MS)), TICK_MS);
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
  }, [still, end, root]);
  return still ? end - FADE_MS : ms;
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

function Step({
  phase,
  tool,
  running,
  done,
  children,
}: {
  phase: Phase;
  tool: string;
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
        <code className="rounded bg-ai/10 px-1.5 py-px font-mono text-[11px] text-ai">{tool}</code>
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

export function ChatDemo({ copy, className }: { copy: ChatDemoCopy; className?: string }) {
  const root = useRef<HTMLElement>(null);
  const reply = tokenize(copy.reply);
  const note = tokenize(copy.replyNote);
  const plan = schedule(reply.length, note.length);
  const ms = useLoopClock(plan.end, root);

  const shown = (span: Span, count: number) =>
    Math.max(0, Math.min(count, Math.ceil((ms - span.start) / TOKEN_MS)));
  const tool = phaseAt(ms, plan.tool);
  const fading = ms > plan.end - FADE_MS;
  const visible = (at: number) => (ms >= at ? "opacity-100" : "opacity-0");

  return (
    <figure
      ref={root}
      aria-label={copy.label}
      className={cn(
        "flex flex-col gap-4 rounded-2xl border bg-card p-4 shadow-[var(--shadow-lift)] md:p-5",
        className,
      )}
    >
      <figcaption className="sr-only">
        {copy.user} {copy.reply.replace(/<\/?b>/g, "")} {copy.replyNote}
      </figcaption>
      <div
        aria-hidden
        className={cn(
          "flex flex-col gap-4 transition-opacity",
          fading ? "opacity-0 duration-500" : "opacity-100 duration-200",
        )}
      >
        <p className="max-w-[86%] self-end rounded-[18px_18px_6px_18px] bg-primary px-[15px] py-2.5 text-[15px] leading-[1.6] text-primary-foreground">
          {copy.user}
        </p>
        <div className="relative flex flex-col gap-2.5 md:pl-[42px]">
          <span className="absolute top-0 left-0 hidden size-[30px] items-center justify-center rounded-full bg-brand-soft md:flex">
            <LogoMark className="size-5" />
          </span>
          <Step
            phase={phaseAt(ms, plan.context)}
            tool="load_context"
            running={copy.stepContext}
            done={copy.stepContextDone}
          >
            <p className="text-[12.5px]">{copy.memory}</p>
          </Step>

          <div
            className={cn(
              "flex flex-col gap-2.5 rounded-[6px_18px_18px_18px] border px-3.5 py-3 text-[14.5px] leading-[1.7] transition-opacity duration-300",
              visible(plan.reply.start),
            )}
          >
            <p>
              <Streamed
                tokens={reply}
                shown={shown(plan.reply, reply.length)}
                streaming={phaseAt(ms, plan.reply) === "run"}
              />
            </p>
            <Step phase={tool} tool="suggest_practice" running={copy.stepTool} done={copy.stepToolDone} />
            <div
              className={cn(
                "flex items-center gap-3 rounded-xl border bg-background/70 px-3 py-2.5 transition-all duration-500",
                tool === "done" ? "translate-y-0 opacity-100" : "translate-y-1 opacity-0",
              )}
            >
              <span className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-brand-soft text-brand">
                <DumbbellIcon className="size-4" />
              </span>
              <span className="min-w-0 flex-1 text-[13.5px] leading-snug font-medium">{copy.practiceCard}</span>
              <span className="inline-flex h-7 shrink-0 items-center gap-1 rounded-full bg-primary px-3 text-xs font-medium text-primary-foreground">
                {copy.practiceStart}
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

          <Step
            phase={phaseAt(ms, plan.grammar)}
            tool="grammar_tagging"
            running={copy.stepGrammar}
            done={copy.stepGrammarDone}
          >
            <p className="flex flex-wrap items-center gap-x-2 text-[12.5px]">
              <s>{copy.wrong}</s>
              <span>→</span>
              <span className="text-success">{copy.right}</span>
              <span className="text-primary">· {copy.rule}</span>
            </p>
          </Step>
          <Step
            phase={phaseAt(ms, plan.memory)}
            tool="reflect_memory"
            running={copy.stepMemory}
            done={copy.stepMemoryDone}
          >
            <p className="text-[12.5px]">{copy.memorySaved}</p>
          </Step>

          <p
            className={cn(
              "flex w-fit items-center gap-1 rounded-full border border-border/70 bg-card/70 py-1 pr-2.5 pl-1.5 text-xs text-foreground/75 transition-opacity duration-500",
              visible(plan.summary),
            )}
          >
            <ChevronRightIcon className="size-3.5 shrink-0" />
            <span>
              {copy.activity} <strong className="text-foreground">{copy.activityRead}</strong> {copy.activityRest}
            </span>
          </p>
        </div>
      </div>
    </figure>
  );
}
