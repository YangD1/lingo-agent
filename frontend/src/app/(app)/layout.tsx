import { redirect } from "next/navigation";
import { Suspense } from "react";

import { AppSidebar } from "@/components/shell/app-sidebar";
import { MobileTabBar, MobileTopBar } from "@/components/shell/mobile-nav";
import { TutorPet } from "@/components/tutor/tutor-pet";
import { ReviewDeckHost } from "@/components/vocab/review-deck-host";
import { ApiError } from "@/lib/api";
import { serverApi } from "@/lib/server-api";
import type { Me } from "@/lib/types";

async function getMe(): Promise<Me> {
  try {
    return await serverApi<Me>("/auth/me");
  } catch (error) {
    if (error instanceof ApiError && error.status === 401) redirect("/session-expired");
    throw error;
  }
}

export default async function AppLayout({ children }: LayoutProps<"/">) {
  const me = await getMe();
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
      <TutorPet />
      {/* Flashcards open over any page (ADR 0038); it reads the URL, so it sits in Suspense. */}
      <Suspense>
        <ReviewDeckHost />
      </Suspense>
    </div>
  );
}
