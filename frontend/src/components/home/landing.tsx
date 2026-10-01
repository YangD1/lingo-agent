import {
  BookOpenIcon,
  BrainIcon,
  ChevronDownIcon,
  ClipboardCheckIcon,
  EyeIcon,
  GitBranchIcon,
  ListChecksIcon,
  type LucideIcon,
  MicIcon,
  ServerIcon,
  SparklesIcon,
} from "lucide-react";
import { getTranslations } from "next-intl/server";
import Link from "next/link";

import { aiPill } from "@/components/ai-pill";
import { LogoMark, Logo } from "@/components/brand/logo";
import { LocaleSwitcher } from "@/components/locale-switcher";
import { buttonVariants } from "@/components/ui/button";
import { cn } from "@/lib/utils";

const REPO_URL = "https://github.com/YangD1/lingo-agent";

const FEATURES = [
  { key: "memory", icon: BrainIcon },
  { key: "grammar", icon: ListChecksIcon },
  { key: "vocab", icon: BookOpenIcon },
  { key: "placement", icon: ClipboardCheckIcon },
  { key: "transparency", icon: EyeIcon },
  { key: "models", icon: ServerIcon },
] as const satisfies readonly { key: string; icon: LucideIcon }[];

function IconChip({ icon: Icon }: { icon: LucideIcon }) {
  return (
    <span className="flex size-9 items-center justify-center rounded-lg bg-brand-soft text-brand-soft-foreground">
      <Icon className="size-[18px]" />
    </span>
  );
}

/**
 * The logged-out home page (home-desktop / home-mobile in docs/design). Everything on it is
 * static: the chat, the confirm card and the AI mark are pictures of the real ones, so the
 * page makes no API calls.
 */
export async function Landing() {
  const t = await getTranslations("home");

  return (
    <div className="flex min-h-svh flex-col">
      <header className="mx-auto flex h-16 w-full max-w-[1100px] items-center gap-2 px-4 md:h-[72px] md:px-6">
        <Logo className="mr-auto text-[15px]" markClassName="size-7" />
        <LocaleSwitcher className="hidden w-[120px] md:block" />
        <Link href="/login" className={buttonVariants({ variant: "ghost" })}>
          {t("login")}
        </Link>
        <Link href="/register" className={buttonVariants()}>
          {t("register")}
        </Link>
      </header>

      <main className="mx-auto flex w-full max-w-[1100px] flex-1 flex-col gap-12 px-4 pt-8 pb-16 md:gap-16 md:px-6 md:pt-16">
        <section className="grid items-center gap-8 md:grid-cols-[1fr_1.05fr] md:gap-12">
          <div className="flex flex-col items-start">
            <span className="inline-flex items-center gap-1.5 rounded-sm border bg-card px-2 py-0.5 text-xs text-muted-foreground">
              <GitBranchIcon className="size-3.5" />
              {t("badge")}
            </span>
            <h1 className="mt-4 text-[34px] leading-tight font-bold tracking-tight md:text-[44px]">
              {t("title")}
            </h1>
            <p className="mt-3 text-lg text-muted-foreground md:text-xl">{t("subtitle")}</p>
            <div className="mt-6 flex gap-2.5">
              <Link href="/register" className={buttonVariants({ size: "lg" })}>
                {t("cta")}
              </Link>
              <Link href="/login" className={buttonVariants({ variant: "outline", size: "lg" })}>
                {t("login")}
              </Link>
            </div>
            <p className="mt-5 text-sm text-muted-foreground">{t("note")}</p>
          </div>
          <ChatDemo />
        </section>

        <section className="flex flex-col gap-5">
          <h2 className="text-xl font-semibold tracking-tight">{t("featuresTitle")}</h2>
          <ul className="grid gap-3 md:grid-cols-3 md:gap-3.5">
            {FEATURES.map(({ key, icon }) => (
              <li key={key} className="flex flex-col gap-3 rounded-xl border bg-card p-4 md:p-5">
                <IconChip icon={icon} />
                <div className="flex flex-col gap-1.5">
                  <h3 className="font-semibold">{t(`features.${key}.title`)}</h3>
                  <p className="text-sm leading-relaxed text-muted-foreground">
                    {t(`features.${key}.body`)}
                  </p>
                </div>
              </li>
            ))}
          </ul>
        </section>

        <section className="grid items-center gap-6 rounded-2xl border bg-card p-5 md:grid-cols-[1fr_0.75fr] md:gap-10 md:p-8">
          <div className="flex flex-col gap-2.5">
            <p className="text-xs text-muted-foreground">{t("trust.eyebrow")}</p>
            <h2 className="text-xl font-semibold tracking-tight md:text-2xl">{t("trust.title")}</h2>
            <p className="leading-relaxed text-muted-foreground">{t("trust.body")}</p>
          </div>
          <div aria-hidden className="flex flex-col gap-3">
            <div className="flex gap-3 rounded-lg border bg-card p-3.5">
              <IconChip icon={BookOpenIcon} />
              <div className="flex flex-col gap-1">
                <p className="text-sm font-semibold">{t("trust.cardTitle")}</p>
                <p className="text-xs text-muted-foreground">{t("trust.cardBody")}</p>
                <div className="mt-2 flex gap-1.5">
                  <span className={buttonVariants({ size: "sm" })}>{t("trust.confirm")}</span>
                  <span className={buttonVariants({ size: "sm", variant: "ghost" })}>
                    {t("trust.decline")}
                  </span>
                </div>
              </div>
            </div>
            <div className="flex items-center gap-3">
              <span className={cn(buttonVariants({ variant: "outline" }), "relative shrink-0")}>
                <MicIcon />
                {t("trust.record")}
                <span
                  className={cn(
                    aiPill,
                    "absolute -top-2 -right-2 ring-2 ring-[var(--card)]",
                  )}
                >
                  <SparklesIcon className="size-2.5" />
                  AI
                </span>
              </span>
              <span className="text-xs text-muted-foreground">{t("trust.hint")}</span>
            </div>
          </div>
        </section>
      </main>

      <footer className="border-t">
        <div className="mx-auto flex w-full max-w-[1100px] flex-wrap items-center gap-x-5 gap-y-3 px-4 py-5 text-sm md:px-6">
          <span className="mr-auto inline-flex items-center gap-2 text-muted-foreground">
            <LogoMark className="size-5" />
            {t("footer.tagline")}
          </span>
          <a href={REPO_URL} className="text-primary hover:underline">
            {t("footer.github")}
          </a>
          <a href={t("footer.docsUrl")} className="text-primary hover:underline">
            {t("footer.docs")}
          </a>
          <LocaleSwitcher className="w-[140px] md:hidden" />
        </div>
      </footer>
    </div>
  );
}

/** A still of one chat turn: user bubble, tutor reply, and "what the tutor did" unfolded. */
async function ChatDemo() {
  const t = await getTranslations("home.demo");
  return (
    <figure
      aria-label={t("label")}
      className="flex flex-col gap-4 rounded-2xl border bg-card p-4 shadow-[var(--shadow-lift)] md:p-5"
    >
      <p className="max-w-[86%] self-end rounded-[18px_18px_6px_18px] bg-primary px-[15px] py-2.5 text-[15px] leading-[1.6] text-primary-foreground">
        {t("user")}
      </p>
      <div className="relative flex flex-col gap-2 md:pl-[42px]">
        <span
          aria-hidden
          className="absolute top-0 left-0 hidden size-[30px] items-center justify-center rounded-full bg-brand-soft md:flex"
        >
          <LogoMark className="size-5" />
        </span>
        <div className="flex flex-col gap-2 rounded-[6px_18px_18px_18px] border px-3.5 py-3 text-[14.5px] leading-[1.7]">
          <p>{t.rich("reply", { b: (chunks) => <strong>{chunks}</strong> })}</p>
          <p>{t("replyNote")}</p>
        </div>
        <p className="flex items-start gap-1 text-xs text-muted-foreground">
          <ChevronDownIcon className="mt-0.5 size-3.5 shrink-0" />
          <span>
            {t("activity")} <strong className="text-foreground">{t("activityRead")}</strong>{" "}
            {t("activityRest")}
          </span>
        </p>
        <ul className="flex flex-col gap-1.5 rounded-lg bg-muted px-3.5 py-2.5 text-[13px]">
          <li className="before:mr-2 before:content-['•']">{t("memory")}</li>
          <li className="flex flex-wrap items-center gap-x-2 before:content-['•']">
            <s className="text-muted-foreground">{t("wrong")}</s>
            <span aria-hidden>→</span>
            <span className="text-success">{t("right")}</span>
            <span className="text-primary">· {t("rule")}</span>
          </li>
        </ul>
      </div>
    </figure>
  );
}
