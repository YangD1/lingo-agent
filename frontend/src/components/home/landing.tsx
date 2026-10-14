import {
  ArrowRightIcon,
  BookOpenIcon,
  BrainIcon,
  ClipboardCheckIcon,
  EyeIcon,
  ListChecksIcon,
  type LucideIcon,
  MicIcon,
  ServerIcon,
  SparklesIcon,
} from "lucide-react";
import { getMessages, getTranslations } from "next-intl/server";
import Link from "next/link";
import type { ReactNode } from "react";

import { aiMark, aiMarkCorner } from "@/components/ai-pill";
import { LingoCat } from "@/components/brand/lingo-cat";
import { Logo, LogoMark } from "@/components/brand/logo";
import { LandingBackdrop } from "@/components/home/landing-backdrop";
import { ChatDemo as AnimatedChatDemo, type ChatDemoCopy, type ChatDemoScene } from "@/components/home/landing-chat-demo";
import {
  AiStill,
  FIXES,
  LevelStill,
  MasteryStill,
  MemoryStill,
  PROVIDERS,
  VocabStill,
} from "@/components/home/landing-stills";
import { LocaleSwitcher } from "@/components/locale-switcher";
import { buttonVariants } from "@/components/ui/button";
import { cn } from "@/lib/utils";

export const REPO_URL = "https://github.com/YangD1/lingo-agent";

const FEATURES = {
  memory: BrainIcon,
  grammar: ListChecksIcon,
  vocab: BookOpenIcon,
  placement: ClipboardCheckIcon,
  transparency: EyeIcon,
  models: ServerIcon,
} as const satisfies Record<string, LucideIcon>;

function IconChip({ icon: Icon }: { icon: LucideIcon }) {
  return (
    <span className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-brand-soft text-brand-soft-foreground">
      <Icon className="size-[18px]" />
    </span>
  );
}

/**
 * The logged-out home page (ADR 0037): an inset hero over a moving fluted-glass backdrop, a
 * chat still overlapping its lower edge, a correction ticker, illustrated feature cards, the
 * transparency section and a dark closing call to action. Everything on it is static: the
 * chat, the confirm card and the stills are pictures of the real ones, so the page makes no
 * API calls.
 */
export async function Landing() {
  const t = await getTranslations("home");
  const feature = (key: keyof typeof FEATURES) => {
    const Icon = FEATURES[key];
    return {
      title: t(`features.${key}.title`),
      body: t(`features.${key}.body`),
      icon: <Icon className="size-[18px] text-brand" />,
    };
  };
  const models = feature("models");

  return (
    <div className="flex min-h-svh flex-col">
      <div className="p-2 md:p-3">
        {/* At least one screen tall whatever the title's length (one line in Chinese, two in
            English); the chat card below rises into its bottom edge. */}
        <section className="relative isolate flex min-h-[calc(100svh-1rem)] flex-col overflow-hidden rounded-[28px] md:min-h-[calc(100svh-1.5rem)] md:rounded-[40px]">
          <LandingBackdrop scene="silk" className="absolute inset-0 -z-20" />
          <div className="absolute inset-0 -z-10 bg-[radial-gradient(56%_52%_at_50%_40%,rgb(252_250_248/0.78),rgb(252_250_248/0.2)_70%,transparent)] dark:bg-[radial-gradient(56%_52%_at_50%_40%,rgb(23_22_27/0.8),rgb(23_22_27/0.3)_70%,transparent)]" />
          <Header />
          <div className="mx-auto flex max-w-[980px] flex-1 flex-col items-center justify-center px-4 pt-12 pb-44 text-center md:pt-16 md:pb-64">
            <span className="glass inline-flex items-center gap-2 rounded-full border px-3.5 py-1.5 text-xs font-medium text-foreground/80">
              <span className="relative flex size-2">
                <span className="absolute inset-0 animate-ping rounded-full bg-brand/60 motion-reduce:animate-none" />
                <span className="relative size-2 rounded-full bg-brand" />
              </span>
              {t("badge")}
            </span>
            <h1 className="mt-7 text-[52px] leading-[0.98] font-extrabold tracking-[-0.05em] text-balance break-keep md:text-[112px]">
              {t("title")}
            </h1>
            <p className="mt-6 max-w-[560px] text-lg text-foreground/75 md:text-[22px] md:leading-snug">
              {t("subtitle")}
            </p>
            <div className="mt-9 flex flex-wrap justify-center gap-3">
              <Link
                href="/register"
                className="inline-flex h-12 items-center gap-2 rounded-full bg-foreground px-7 text-[15px] font-medium text-background shadow-[0_12px_30px_-10px_rgb(28_27_34/0.6)] transition-transform hover:-translate-y-0.5"
              >
                {t("cta")}
                <ArrowRightIcon className="size-4" />
              </Link>
              <Link
                href="/login"
                className="glass inline-flex h-12 items-center rounded-full border px-7 text-[15px] font-medium transition-transform hover:-translate-y-0.5"
              >
                {t("login")}
              </Link>
            </div>
          </div>
        </section>

        <div className="relative z-10 mx-auto -mt-32 max-w-[760px] px-2 md:-mt-44">
          <LingoCat
            mood="idle"
            size={80}
            label=""
            className="absolute -top-[66px] right-10 hidden md:block"
          />
          <ChatDemo className="rounded-[28px] border-white/60 p-5 shadow-[0_40px_80px_-30px_rgb(200_68_31/0.45),0_2px_6px_rgb(28_27_34/0.06)] md:p-7 dark:border-white/10" />
          <p className="mt-5 text-center text-sm text-muted-foreground">{t("note")}</p>
        </div>
      </div>

      <div
        aria-hidden
        className="mt-14 overflow-hidden border-y bg-card/60 py-5 [mask-image:linear-gradient(90deg,transparent,black_12%,black_88%,transparent)]"
      >
        <div className="flex w-max animate-marquee motion-reduce:animate-none">
          {[0, 1].map((copy) => (
            <ul key={copy} className="flex shrink-0 items-center">
              {FIXES.map(([wrong, right]) => (
                <li key={wrong} className="flex items-center gap-3 px-7 text-lg md:text-xl">
                  <s className="text-muted-foreground decoration-brand/50 decoration-2">{wrong}</s>
                  <ArrowRightIcon className="size-4 text-brand" />
                  <span className="font-semibold tracking-tight">{right}</span>
                  <span className="ml-7 size-1.5 rounded-full bg-brand/40" />
                </li>
              ))}
            </ul>
          ))}
        </div>
      </div>

      <main className="mx-auto flex w-full max-w-[1160px] flex-1 flex-col gap-28 px-4 pt-24 pb-24 md:px-6">
        <section className="flex flex-col gap-12">
          <div className="flex flex-col gap-4 md:flex-row md:items-end md:justify-between">
            <h2 className="max-w-[640px] text-[36px] leading-[1.05] font-bold tracking-[-0.035em] md:text-[56px]">
              {t("featuresTitle")}
            </h2>
            <p className="max-w-[340px] text-muted-foreground">{t("subtitle")}</p>
          </div>
          <ul className="grid grid-cols-1 gap-4 md:grid-cols-6">
            <FeatureCard
              className="bg-linear-to-br from-brand-soft/70 via-card to-card md:col-span-4"
              still={<MemoryStill />}
              {...feature("memory")}
            />
            <FeatureCard className="md:col-span-2" still={<MasteryStill />} {...feature("grammar")} />
            <FeatureCard className="md:col-span-2" still={<VocabStill />} {...feature("vocab")} />
            <FeatureCard className="md:col-span-2" still={<LevelStill />} {...feature("placement")} />
            <FeatureCard className="md:col-span-2" still={<AiStill />} {...feature("transparency")} />
            <li className="dark relative isolate flex flex-col gap-8 overflow-hidden rounded-[28px] border bg-background p-7 text-foreground md:col-span-6 md:flex-row md:items-center md:p-10">
              <span
                aria-hidden
                className="absolute -right-24 -bottom-32 -z-10 size-[420px] rounded-full bg-brand/30 blur-3xl"
              />
              <span
                aria-hidden
                className="absolute top-[-40%] left-1/3 -z-10 size-[360px] rounded-full bg-ai/25 blur-3xl"
              />
              <div className="flex max-w-[420px] flex-col gap-2">
                <h3 className="flex items-center gap-2.5 text-xl font-semibold tracking-tight">
                  {models.icon}
                  {models.title}
                </h3>
                <p className="text-sm leading-relaxed text-muted-foreground">{models.body}</p>
              </div>
              <ul
                aria-hidden
                className="flex flex-1 flex-wrap gap-x-7 gap-y-2 text-2xl font-semibold tracking-tight text-foreground/35 md:justify-end md:text-3xl"
              >
                {PROVIDERS.map((p) => (
                  <li key={p} className="transition-colors hover:text-foreground">
                    {p}
                  </li>
                ))}
              </ul>
            </li>
          </ul>
        </section>

        <section className="relative isolate grid grid-cols-1 items-center gap-10 overflow-hidden rounded-[40px] border bg-linear-to-br from-brand-soft via-card to-[oklch(0.95_0.03_285)] p-7 md:grid-cols-[1fr_0.85fr] md:gap-16 md:p-14 dark:to-[oklch(0.26_0.05_285)]">
          <div className="flex flex-col gap-4">
            <p className="text-sm font-semibold text-primary">{t("trust.eyebrow")}</p>
            <h2 className="text-[30px] leading-[1.1] font-bold tracking-[-0.03em] md:text-[44px]">
              {t("trust.title")}
            </h2>
            <p className="text-muted-foreground md:text-lg">{t("trust.body")}</p>
          </div>
          <TrustStill />
        </section>

        <section className="dark relative isolate overflow-hidden rounded-[40px] px-6 py-20 text-center text-foreground md:py-32">
          <LandingBackdrop scene="ink" className="absolute inset-0 -z-10" />
          <LingoCat mood="hop" size={72} label="" className="mx-auto" />
          <h2 className="mx-auto mt-6 max-w-[760px] text-[40px] leading-[1] font-extrabold tracking-[-0.045em] md:text-[80px]">
            {t("closingTitle")}
          </h2>
          <p className="mx-auto mt-5 max-w-[520px] text-white/75 md:text-lg">{t("subtitle")}</p>
          <Link
            href="/register"
            className="mt-9 inline-flex h-12 items-center gap-2 rounded-full bg-white px-7 text-[15px] font-medium text-[#1C1B22] transition-transform hover:-translate-y-0.5"
          >
            {t("cta")}
            <ArrowRightIcon className="size-4" />
          </Link>
        </section>
      </main>

      <Footer />
    </div>
  );
}

async function Header() {
  const t = await getTranslations("home");
  return (
    <header className="mx-auto flex h-16 w-full max-w-[1160px] items-center gap-2 px-4 md:h-[72px] md:px-6">
      <Logo className="mr-auto text-[15px]" markClassName="size-7" />
      <LocaleSwitcher className="hidden w-[120px] md:flex" />
      <Link href="/login" className={buttonVariants({ variant: "ghost" })}>
        {t("login")}
      </Link>
      <Link href="/register" className={buttonVariants()}>
        {t("register")}
      </Link>
    </header>
  );
}

async function Footer() {
  const t = await getTranslations("home");
  return (
    <footer className="border-t">
      <div className="mx-auto flex w-full max-w-[1160px] flex-wrap items-center gap-x-5 gap-y-3 px-4 py-6 text-sm md:px-6">
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
  );
}

function FeatureCard({
  className,
  still,
  title,
  body,
  icon,
}: {
  className?: string;
  still: ReactNode;
  title: string;
  body: string;
  icon: ReactNode;
}) {
  return (
    <li
      className={cn(
        "flex flex-col gap-6 overflow-hidden rounded-[28px] border bg-card p-6 shadow-(--shadow-card) transition-[translate,box-shadow] duration-300 hover:-translate-y-1 hover:shadow-(--shadow-pop) motion-reduce:hover:translate-y-0 md:p-7",
        className,
      )}
    >
      <div className="flex-1">{still}</div>
      <div className="flex flex-col gap-2">
        <h3 className="flex items-center gap-2.5 text-lg font-semibold tracking-tight">
          {icon}
          {title}
        </h3>
        <p className="text-sm leading-relaxed text-muted-foreground">{body}</p>
      </div>
    </li>
  );
}

/** The confirm card and an AI-marked button, as pictures of the real ones. */
async function TrustStill() {
  const t = await getTranslations("home.trust");
  return (
    <div
      aria-hidden
      className="flex rotate-[-1.5deg] flex-col gap-3 rounded-3xl bg-card/70 p-4 shadow-(--shadow-pop) backdrop-blur"
    >
      <div className="flex gap-3 rounded-xl border bg-card p-4 shadow-(--shadow-card)">
        <IconChip icon={BookOpenIcon} />
        <div className="flex flex-col gap-1">
          <p className="text-sm font-semibold">{t("cardTitle")}</p>
          <p className="text-xs text-muted-foreground">{t("cardBody")}</p>
          <div className="mt-2 flex gap-1.5">
            <span className={buttonVariants({ size: "sm" })}>{t("confirm")}</span>
            <span className={buttonVariants({ size: "sm", variant: "ghost" })}>{t("decline")}</span>
          </div>
        </div>
      </div>
      <div className="flex items-center gap-3">
        <span className={cn(buttonVariants({ variant: "outline" }), "relative shrink-0 bg-card")}>
          <MicIcon />
          {t("record")}
          <span className={cn(aiMark, aiMarkCorner, "bg-card")}>
            <SparklesIcon />
          </span>
        </span>
        <span className="text-xs text-muted-foreground">{t("hint")}</span>
      </div>
    </div>
  );
}

/** A still of one chat turn: user bubble, tutor reply, and "what the tutor did" unfolded. */
/** Copy for the animated example (landing-chat-demo.tsx), translated on the server. */
async function ChatDemo({ className }: { className?: string }) {
  const t = await getTranslations("home.demo");
  const { scenes } = (await getMessages()).home.demo;
  const copy: ChatDemoCopy = {
    label: t("label"),
    topics: t("topics"),
    stepContext: t("stepContext"),
    activity: t("activity"),
    // Keyed by name in the catalogs so both languages keep the same keys; played in order.
    scenes: Object.values(scenes).map((scene) => ({
      ...scene,
      tool: { ...scene.tool, icon: scene.tool.icon as ChatDemoScene["tool"]["icon"] },
      after: Object.values(scene.after),
    })),
  };
  return <AnimatedChatDemo copy={copy} className={className} />;
}
