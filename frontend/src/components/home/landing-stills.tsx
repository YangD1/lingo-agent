import { ArrowRightIcon, BrainIcon, SparklesIcon } from "lucide-react";
import { getTranslations } from "next-intl/server";

import { cn } from "@/lib/utils";

/**
 * Small pictures of the product for the home page's feature cards. Like ChatDemo they are
 * static illustration (hidden from screen readers; the card text says the same thing), and the
 * English sample data is part of the picture, so it is not translated.
 */

export const FIXES = [
  ["I go", "I went"],
  ["He don't", "He doesn't"],
  ["more better", "better"],
  ["informations", "information"],
  ["I'm agree", "I agree"],
  ["depend of", "depend on"],
  ["since three years", "for three years"],
  ["discuss about it", "discuss it"],
] as const;

export const PROVIDERS = ["DeepSeek", "OpenAI", "Anthropic", "Qwen", "SiliconFlow", "Ollama"] as const;

const MASTERY = [
  ["Past simple", 92],
  ["Articles", 71],
  ["Present perfect", 54],
  ["Conditionals", 33],
  ["Phrasal verbs", 18],
] as const;

const LEVELS = ["A1", "A2", "B1", "B2", "C1", "C2"] as const;

/* Heat ramp from globals.css: weak → strong. */
function heat(pct: number): string {
  if (pct >= 80) return "var(--heat-4)";
  if (pct >= 60) return "var(--heat-3)";
  if (pct >= 40) return "var(--heat-2)";
  return "var(--heat-1)";
}

export async function MemoryStill() {
  const t = await getTranslations("home.memoryStill");
  return (
    <ul aria-hidden className="flex flex-col gap-2 text-sm">
      <li className="flex items-center gap-2.5 rounded-xl border bg-background/70 px-3 py-2.5">
        <BrainIcon className="size-4 shrink-0 text-brand" />
        <span className="truncate">{t("memory")}</span>
      </li>
      <li className="flex items-center gap-2.5 rounded-xl border bg-background/70 px-3 py-2.5">
        <span className="size-4 shrink-0 rounded-full bg-primary/20 ring-4 ring-primary/10" />
        <s className="text-muted-foreground">{t("wrong")}</s>
        <ArrowRightIcon className="size-3.5 text-muted-foreground" />
        <span className="font-medium text-success">{t("right")}</span>
        <span className="ml-auto truncate text-xs text-muted-foreground">{t("rule")}</span>
      </li>
      <li className="flex items-center gap-2.5 rounded-xl border border-dashed px-3 py-2.5 text-muted-foreground">
        <SparklesIcon className="size-4 shrink-0 text-ai" />
        <span className="truncate">{t("activity")}</span>
      </li>
    </ul>
  );
}

export function MasteryStill() {
  return (
    <ul aria-hidden className="flex flex-col gap-2.5 text-xs">
      {MASTERY.map(([name, pct]) => (
        <li key={name} className="grid grid-cols-[1fr_auto] items-center gap-x-3 gap-y-1">
          <span className="font-medium">{name}</span>
          <span className="font-mono text-muted-foreground tabular-nums">{pct}%</span>
          <span className="col-span-2 h-1.5 overflow-hidden rounded-full bg-muted">
            <span
              className="block h-full rounded-full"
              style={{ width: `${pct}%`, background: heat(pct) }}
            />
          </span>
        </li>
      ))}
    </ul>
  );
}

export function VocabStill() {
  return (
    <div aria-hidden className="relative h-[120px]">
      <div className="absolute inset-x-6 top-0 h-full rotate-[-4deg] rounded-2xl border bg-muted/60" />
      <div className="absolute inset-x-3 top-1 h-full rotate-[2.5deg] rounded-2xl border bg-brand-soft" />
      <div className="absolute inset-x-0 top-2 flex h-full flex-col justify-between rounded-2xl border bg-card p-4 shadow-(--shadow-card)">
        <div>
          <p className="text-lg font-semibold tracking-tight">resilient</p>
          <p className="font-mono text-xs text-muted-foreground">/rɪˈzɪliənt/ · adj.</p>
        </div>
        <div className="flex gap-1.5 font-mono text-[10px]">
          {["Again", "Hard", "Good", "Easy"].map((r, i) => (
            <span
              key={r}
              className={cn(
                "rounded-md border px-1.5 py-0.5",
                i === 2 && "border-brand bg-brand text-primary-foreground",
              )}
            >
              {r}
            </span>
          ))}
        </div>
      </div>
    </div>
  );
}

export function LevelStill() {
  return (
    <div aria-hidden className="flex flex-col gap-3">
      <div className="grid grid-cols-6 gap-1">
        {LEVELS.map((l, i) => (
          <span
            key={l}
            className={cn(
              "flex items-end justify-center rounded-lg pb-1.5 font-mono text-xs",
              i < 3 ? "bg-brand-soft text-brand-soft-foreground" : "bg-muted text-muted-foreground",
              i === 2 && "bg-brand text-primary-foreground shadow-(--shadow-button)",
            )}
            style={{ height: `${36 + i * 8}px` }}
          >
            {l}
          </span>
        ))}
      </div>
      <p className="font-mono text-[11px] text-muted-foreground">B1 · ~3,400 words · 9:42</p>
    </div>
  );
}

export function AiStill() {
  return (
    <div aria-hidden className="flex flex-col gap-2 font-mono text-[11px]">
      <span className="inline-flex w-fit items-center gap-1.5 rounded-full bg-ai/10 px-2.5 py-1 text-ai">
        <SparklesIcon className="size-3.5" /> AI
      </span>
      <div className="rounded-xl border bg-background/70 p-3 leading-relaxed text-muted-foreground">
        <p>
          <span className="text-foreground">chat.reply</span> · deepseek-chat
        </p>
        <p>
          <span className="text-foreground">memory.extract</span> · qwen-plus
        </p>
        <p className="mt-1 text-foreground">≈ 1.8k tokens / turn</p>
      </div>
    </div>
  );
}
