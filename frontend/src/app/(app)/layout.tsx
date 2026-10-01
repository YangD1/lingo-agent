import { getTranslations } from "next-intl/server";
import Link from "next/link";
import { redirect } from "next/navigation";

import { Logo } from "@/components/brand/logo";
import { LocaleSwitcher } from "@/components/locale-switcher";
import { LogoutButton } from "@/components/logout-button";
import { ThemeSwitcher } from "@/components/theme/theme-switcher";
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
  const [me, t] = await Promise.all([getMe(), getTranslations("nav")]);
  return (
    <div className="flex h-dvh flex-col">
      <header className="flex items-center gap-4 border-b px-4 py-2">
        <Logo />
        <nav className="flex gap-3 text-sm">
          <Link href="/dashboard">{t("dashboard")}</Link>
          <Link href="/chat">{t("chat")}</Link>
          <Link href="/vocab">{t("vocab")}</Link>
          <Link href="/memory">{t("memory")}</Link>
          <Link href="/learner">{t("learner")}</Link>
          <Link href="/placement">{t("placement")}</Link>
          <Link href="/settings">{t("settings")}</Link>
        </nav>
        <div className="ml-auto flex items-center gap-3">
          <span className="text-sm text-muted-foreground" data-testid="current-user">
            {me.user.display_name || me.user.email}
          </span>
          <LocaleSwitcher />
          <ThemeSwitcher />
          <LogoutButton />
        </div>
      </header>
      <div className="flex min-h-0 flex-1">{children}</div>
    </div>
  );
}
