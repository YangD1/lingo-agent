"use client";

import { SparklesIcon } from "lucide-react";
import { useFormatter, useTranslations } from "next-intl";
import { useEffect, useState } from "react";

import { aiMark, aiMarkCorner } from "@/components/ai-pill";
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
  corner = false,
  className,
}: {
  /** Several when one control leads to more than one (e.g. attach: images and PDFs). */
  feature: AiFeature | readonly AiFeature[];
  /** Pin to the top-right corner of a `relative` parent, ringed off with the page colour. */
  corner?: boolean;
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
          aiMark,
          "cursor-help hover:bg-[color-mix(in_oklab,var(--ai)_14%,var(--card))]",
          corner && aiMarkCorner,
          className,
        )}
      >
        <SparklesIcon aria-hidden />
      </PopoverTrigger>
      <PopoverContent
        className="max-h-[70vh] w-[340px] max-w-[calc(100vw-32px)] overflow-y-auto text-xs"
        data-testid="ai-badge-details"
      >
        {features.map((f) => (
          <section key={f} className="flex flex-col gap-2">
            <p className="flex items-start gap-2 text-[13px] leading-[1.6]">
              <span aria-hidden className={cn(aiMark, "mt-1")}>
                <SparklesIcon />
              </span>
              <span>{t(`feature.${f}`)}</span>
            </p>
            {loaded.status === "ok" && (
              <ul className="flex flex-col divide-y">
                {callsOf(loaded.data, f).map((call, i) => (
                  <CallLine key={`${call.task}-${i}`} call={call} />
                ))}
              </ul>
            )}
          </section>
        ))}
        {loaded.status === "loading" && <p className="text-muted-foreground">{t("loading")}</p>}
        {loaded.status === "error" && <p className="text-destructive">{t("failed")}</p>}
        <p className="border-t pt-2 text-muted-foreground">{t("footer")}</p>
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
      : call.characters !== null
        ? t("characters", { characters: n(call.characters) })
        : t("tokens", { input: n(call.input_tokens), output: n(call.output_tokens) });

  return (
    <li className="flex flex-col gap-0.5 py-2 first:pt-0 last:pb-0">
      <span className="flex items-baseline gap-2">
        <span className="font-semibold">
          {isAiTask(call.task) ? t(`task.${call.task}`) : call.task}
        </span>
        <span className="ml-auto font-mono text-[11px] text-muted-foreground">
          {t(`timing.${call.timing}`)}
        </span>
      </span>
      <span className="tabular-nums">
        {amount}
        {call.per !== "call" && ` ${t(`per.${call.per}`)}`}
      </span>
      <span className={cn("text-muted-foreground", call.model && "font-mono")}>
        {call.model ? t("model", { model: call.model }) : t("noModel")}
      </span>
      <span className="text-[11px] text-muted-foreground">
        {call.source === "history" ? t("fromHistory", { samples: call.samples }) : t("fromDefault")}
      </span>
    </li>
  );
}
