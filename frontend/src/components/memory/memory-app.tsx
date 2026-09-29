"use client";

import { MemoryListSection } from "./memory-list-section";
import { ProfileSection } from "./profile-section";

/** "What the tutor remembers about you" (ADR 0009): all of it viewable, editable, deletable. */
export function MemoryApp() {
  return (
    <div className="flex-1 overflow-y-auto">
      <div className="mx-auto flex max-w-3xl flex-col gap-6 p-4 md:p-8">
        <ProfileSection />
        <MemoryListSection kind="fact" />
        <MemoryListSection kind="episode" />
      </div>
    </div>
  );
}
