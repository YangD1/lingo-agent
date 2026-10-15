"use client";

import { CompassIcon } from "lucide-react";
import Link from "next/link";
import { useTranslations } from "next-intl";

import { buttonVariants } from "@/components/ui/button";
import { SETUP_PATH } from "@/lib/setup";
import { cn } from "@/lib/utils";

/** Opens the setup guide again from the user menu (ADR 0042 §4). */
export function SetupLink({ className }: { className?: string }) {
  const t = useTranslations("nav");
  return (
    <Link
      href={SETUP_PATH}
      data-testid="open-setup"
      className={cn(buttonVariants({ variant: "ghost", size: "sm" }), "justify-start", className)}
    >
      <CompassIcon />
      {t("setup")}
    </Link>
  );
}
