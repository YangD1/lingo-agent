import { redirect } from "next/navigation";

import { AppSidebar } from "@/components/shell/app-sidebar";
import { MobileTabBar, MobileTopBar } from "@/components/shell/mobile-nav";
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
        <div className="flex min-h-0 flex-1">{children}</div>
        <MobileTabBar user={user} />
      </div>
    </div>
  );
}
