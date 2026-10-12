"use client";

import { useTranslations } from "next-intl";
import { useRouter } from "next/navigation";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

import { JoinPanel } from "./membership-section";

/** The page an invite link opens (ADR 0031 §2): login first (the proxy), then agree. */
export function JoinApp({ code }: { code: string }) {
  const t = useTranslations("settings.org.join");
  const router = useRouter();
  return (
    <div className="flex-1 overflow-y-auto">
      <div className="mx-auto flex max-w-2xl flex-col gap-4 p-4 md:px-10 md:py-8">
        <Card>
          <CardHeader>
            <CardTitle>{t("title")}</CardTitle>
            <CardDescription>{t("description")}</CardDescription>
          </CardHeader>
          <CardContent>
            <JoinPanel code={code} onJoined={() => router.push("/settings#membership")} />
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
