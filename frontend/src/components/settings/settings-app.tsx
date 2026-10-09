"use client";

import {
  CalendarClock,
  ChartColumn,
  Eye,
  ListOrdered,
  type LucideIcon,
  Plug,
  Volume2,
} from "lucide-react";
import { useTranslations } from "next-intl";
import { type RefObject, useEffect, useRef, useState } from "react";

import { api } from "@/lib/api";
import type { Connection, Presets } from "@/lib/types";
import { cn } from "@/lib/utils";

import { BackgroundSection } from "./background-section";
import { RouteSection } from "./route-section";
import { ConnectionsSection } from "./connections-section";
import { DisplaySection } from "./display-section";
import { ReadAloudSection } from "./read-aloud-section";
import { UsageSection } from "./usage-section";

// The page's sections, in order: the ids are the cards' anchors.
const SECTIONS = [
  { id: "connections", icon: Plug },
  { id: "routes", icon: ListOrdered },
  { id: "display", icon: Eye },
  { id: "read-aloud", icon: Volume2 },
  { id: "background", icon: CalendarClock },
  { id: "usage", icon: ChartColumn },
] as const satisfies readonly { id: string; icon: LucideIcon }[];

export function SettingsApp() {
  const tNav = useTranslations("nav");
  const [presets, setPresets] = useState<Presets | null>(null);
  const [connections, setConnections] = useState<Connection[] | null>(null);
  const scroller = useRef<HTMLDivElement>(null);

  useEffect(() => {
    api<Presets>("/provider-presets").then(setPresets, () => {});
    api<Connection[]>("/tenant/connections").then(setConnections, () => {});
  }, []);

  return (
    <div ref={scroller} className="flex-1 overflow-y-auto">
      <div className="mx-auto flex max-w-5xl flex-col gap-3.5 p-4 md:gap-4 md:px-10 md:py-8">
        <h1 className="text-[26px] font-bold tracking-tight max-md:sr-only">{tNav("settings")}</h1>
        <div className="lg:grid lg:grid-cols-[minmax(0,1fr)_10rem] lg:gap-8">
          <div className="flex min-w-0 flex-col gap-3.5 md:gap-4">
            <SettingsToc scroller={scroller} className="lg:hidden" />
            {presets && connections && (
              <>
                <ConnectionsSection
                  presets={presets}
                  connections={connections}
                  onChange={setConnections}
                />
                <div id="routes" className="scroll-mt-14 lg:scroll-mt-4">
                  <RouteSection task="chat" connections={connections} />
                </div>
                <div className="grid gap-3.5 md:grid-cols-2 md:gap-4">
                  <RouteSection task="reflect" connections={connections} compact />
                  <RouteSection task="vision" connections={connections} compact />
                  <RouteSection task="asr" connections={connections} compact />
                  <RouteSection task="tts" connections={connections} compact />
                </div>
              </>
            )}
            <DisplaySection />
            <ReadAloudSection />
            <BackgroundSection />
            <UsageSection />
          </div>
          <aside className="max-lg:hidden">
            <SettingsToc scroller={scroller} className="sticky top-4" vertical />
          </aside>
        </div>
      </div>
    </div>
  );
}

/**
 * "On this page": a sticky list beside the cards on wide screens, a row of scrollable tabs
 * above them on narrow ones. The current section is the last one whose top has scrolled past.
 */
function SettingsToc({
  scroller,
  vertical = false,
  className,
}: {
  scroller: RefObject<HTMLDivElement | null>;
  vertical?: boolean;
  className?: string;
}) {
  const t = useTranslations("settings.toc");
  const [current, setCurrent] = useState<string>(SECTIONS[0].id);

  useEffect(() => {
    const root = scroller.current;
    if (!root) return;
    const onScroll = () => {
      const top = root.getBoundingClientRect().top + 80;
      let active: string = SECTIONS[0].id;
      for (const { id } of SECTIONS) {
        const el = document.getElementById(id);
        if (el && el.getBoundingClientRect().top <= top) active = id;
      }
      // At the bottom, the last sections may never reach the top: pick the last one.
      if (root.scrollTop + root.clientHeight >= root.scrollHeight - 4) {
        active = SECTIONS[SECTIONS.length - 1].id;
      }
      setCurrent(active);
    };
    root.addEventListener("scroll", onScroll, { passive: true });
    return () => root.removeEventListener("scroll", onScroll);
  }, [scroller]);

  return (
    <nav
      aria-label={t("title")}
      className={cn(
        vertical
          ? "flex flex-col gap-0.5"
          : "sticky top-0 z-10 -mx-4 -mt-1 flex gap-1.5 overflow-x-auto bg-background px-4 py-2 md:-mx-10 md:px-10",
        className,
      )}
    >
      {vertical && (
        <p className="mb-1 px-2.5 text-xs font-semibold text-muted-foreground">{t("title")}</p>
      )}
      {SECTIONS.map(({ id, icon: Icon }) => (
        <a
          key={id}
          href={`#${id}`}
          aria-current={current === id ? "location" : undefined}
          onClick={() => setCurrent(id)}
          className={cn(
            "flex shrink-0 items-center gap-2 text-[13px] font-medium whitespace-nowrap text-muted-foreground transition-colors hover:text-foreground aria-[current]:bg-brand-soft aria-[current]:text-brand-soft-foreground",
            vertical ? "rounded-md px-2.5 py-1.5" : "h-8 rounded-full border px-3 aria-[current]:border-transparent",
          )}
        >
          <Icon className="size-4" />
          {t(id)}
        </a>
      ))}
    </nav>
  );
}
