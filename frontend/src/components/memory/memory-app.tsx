"use client";

import { useTranslations } from "next-intl";

import { MemoryListSection } from "./memory-list-section";
import { ProfileSection } from "./profile-section";

/** "What the tutor remembers about you" (ADR 0009): all of it viewable, editable, deletable. */
export function MemoryApp() {
  const tNav = useTranslations("nav");
  return (
    <div className="flex-1 overflow-y-auto">
      <div className="mx-auto flex max-w-3xl flex-col gap-3.5 p-4 md:gap-4 md:px-10 md:py-8">
        <h1 className="text-[26px] font-bold tracking-tight max-md:sr-only">{tNav("memory")}</h1>
        <ProfileSection />
        <MemoryListSection kind="fact" />
        <MemoryListSection kind="episode" />
      </div>
    </div>
  );
}
