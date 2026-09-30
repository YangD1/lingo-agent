"use client";

import { useFormatter, useTranslations } from "next-intl";
import { useEffect, useState } from "react";

import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import {
  type AiFeature,
  type CallEstimate,
  type UsageEstimates,
  callsOf,
  isAiTask,
  loadEstimates,
} from "@/lib/ai-usage";
import { cn } from "@/lib/utils";

type Loaded = { status: "loading" } | { status: "ok"; data: UsageEstimates } | { status: "error" };

/** Fetches (through the shared cache) only once the popover has been opened. */
function useEstimates(enabled: boolean): Loaded {
  const [loaded, setLoaded] = useState<Loaded>({ status: "loading" });
  useEffect(() => {
    if (!enabled) return;
    let live = true;
    loadEstimates().then(
      (data) => live && setLoaded({ status: "ok", data }),
      () => live && setLoaded({ status: "error" }),
    );
    return () => {
      live = false;
    };
  }, [enabled]);
  return loaded;
}

/**
 * Marks a feature that calls a model (ADR 0014). Hover, focus or tap shows what the AI
 * does there and roughly how many tokens each call takes.
 */
export function AiBadge({
  feature,
  className,
}: {
  /** Several when one control leads to more than one (e.g. attach: images and PDFs). */
  feature: AiFeature | readonly AiFeature[];
  className?: string;
}) {
  const t = useTranslations("aiBadge");
  const features: readonly AiFeature[] = typeof feature === "string" ? [feature] : feature;
  const [open, setOpen] = useState(false);
  const [opened, setOpened] = useState(false);
  const loaded = useEstimates(opened);

  return (
    <Popover
      open={open}
      onOpenChange={(next) => {
        setOpen(next);
        if (next) setOpened(true);
      }}
    >
      <PopoverTrigger
        openOnHover
        delay={150}
        aria-label={t("label")}
        data-testid={`ai-badge-${features.join("-")}`}
        className={cn(
          "inline-flex h-4 shrink-0 cursor-help items-center rounded-sm border border-violet-500/40 bg-violet-500/10 px-1 text-[10px] leading-none font-semibold tracking-wide text-violet-700 dark:text-violet-300",
          className,
        )}
      >
        AI
      </PopoverTrigger>
      <PopoverContent className="max-h-[70vh] w-80 overflow-y-auto text-xs" data-testid="ai-badge-details">
        {features.map((f) => (
          <section key={f} className="flex flex-col gap-2">
            <p className="text-sm">{t(`feature.${f}`)}</p>
            {loaded.status === "ok" && (
              <ul className="flex flex-col gap-2">
                {callsOf(loaded.data, f).map((call, i) => (
                  <CallLine key={`${call.task}-${i}`} call={call} />
                ))}
              </ul>
            )}
          </section>
        ))}
        {loaded.status === "loading" && <p className="text-muted-foreground">{t("loading")}</p>}
        {loaded.status === "error" && <p className="text-destructive">{t("failed")}</p>}
        <p className="text-muted-foreground">{t("footer")}</p>
      </PopoverContent>
    </Popover>
  );
}

function CallLine({ call }: { call: CallEstimate }) {
  const t = useTranslations("aiBadge");
  const format = useFormatter();
  const n = (value: number) => format.number(value);
  const amount =
    call.audio_seconds !== null
      ? t("audio", { seconds: n(call.audio_seconds) })
      : t("tokens", { input: n(call.input_tokens), output: n(call.output_tokens) });

  return (
    <li className="flex flex-col gap-0.5 rounded-md bg-muted/50 px-2 py-1.5">
      <span className="font-medium">
        {isAiTask(call.task) ? t(`task.${call.task}`) : call.task}
        <span className="font-normal text-muted-foreground"> · {t(`timing.${call.timing}`)}</span>
      </span>
      <span>
        {amount}
        {call.per !== "call" && ` ${t(`per.${call.per}`)}`}
      </span>
      <span className="text-muted-foreground">
        {call.source === "history" ? t("fromHistory", { samples: call.samples }) : t("fromDefault")}
        {" · "}
        {call.model ? t("model", { model: call.model }) : t("noModel")}
      </span>
    </li>
  );
}
