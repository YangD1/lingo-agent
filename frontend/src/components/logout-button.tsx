"use client";

import { LogOutIcon } from "lucide-react";
import { useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";
import { LOGIN_PATH } from "@/lib/auth";

export function LogoutButton({ compact = false }: { compact?: boolean }) {
  const t = useTranslations("nav");
  const router = useRouter();
  const [pending, setPending] = useState(false);

  async function logout() {
    setPending(true);
    try {
      await api("/auth/logout", { method: "POST" });
    } finally {
      // Even if the call failed, leave the app; the proxy/layout re-check on next visit.
      router.replace(LOGIN_PATH);
      router.refresh();
    }
  }

  return (
    <Button
      variant="ghost"
      size={compact ? "icon-sm" : "sm"}
      onClick={logout}
      disabled={pending}
      aria-label={compact ? t("logout") : undefined}
      title={compact ? t("logout") : undefined}
      className={compact ? undefined : "justify-start"}
    >
      <LogOutIcon />
      {!compact && t("logout")}
    </Button>
  );
}
