import { getTranslations } from "next-intl/server";
import Link from "next/link";

import { LocaleSwitcher } from "@/components/locale-switcher";
import { buttonVariants } from "@/components/ui/button";

export default async function Home() {
  const t = await getTranslations();
  return (
    <main className="flex flex-1 flex-col items-center justify-center gap-6 p-8 text-center">
      <div className="absolute top-4 right-4">
        <LocaleSwitcher />
      </div>
      <h1 className="text-3xl font-semibold">{t("metadata.title")}</h1>
      <p className="max-w-md text-muted-foreground">{t("home.tagline")}</p>
      <div className="flex gap-3">
        <Link href="/login" className={buttonVariants()}>
          {t("home.login")}
        </Link>
        <Link href="/register" className={buttonVariants({ variant: "outline" })}>
          {t("home.register")}
        </Link>
      </div>
    </main>
  );
}
