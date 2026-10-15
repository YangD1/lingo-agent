import { redirect } from "next/navigation";
import { Suspense } from "react";

import { AppSidebar } from "@/components/shell/app-sidebar";
import { MobileTabBar, MobileTopBar } from "@/components/shell/mobile-nav";
import { TutorPet } from "@/components/tutor/tutor-pet";
import { ReviewDeckHost } from "@/components/vocab/review-deck-host";
import { getMe } from "@/lib/server-me";
import { SETUP_PATH } from "@/lib/setup";

export default async function AppLayout({ children }: LayoutProps<"/">) {
  const me = await getMe();
  // A new account sets up first (ADR 0042 §1); the guide and invite links live outside this layout.
  if (me.user.setup_completed_at === null) redirect(SETUP_PATH);
  const user = { name: me.user.display_name || me.user.email, email: me.user.email };
  return (
    <div className="flex h-dvh">
      <AppSidebar user={user} />
      <div className="flex min-w-0 flex-1 flex-col">
        <MobileTopBar />
        {/* relative + overflow-hidden: absolutely positioned descendants without a positioned
            ancestor (e.g. an sr-only <caption>) would otherwise stretch <body> and add a
            second, page-level scrollbar. */}
        <main className="relative flex min-h-0 flex-1 overflow-hidden">{children}</main>
        <MobileTabBar user={user} />
      </div>
      {/* Both read the URL (the pet makes way for flashcards), so they sit in Suspense.
          Flashcards open over any page (ADR 0038). */}
      <Suspense>
        <TutorPet />
        <ReviewDeckHost />
      </Suspense>
    </div>
  );
}
