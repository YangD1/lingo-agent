import { ArrowRightIcon } from "lucide-react";
import { getLocale, getMessages, getTranslations } from "next-intl/server";
import Link from "next/link";

import { GitHubMark, REPO_URL } from "@/components/brand/github";
import { LogoMark } from "@/components/brand/logo";
import { DemoSection } from "@/components/home/landing-demo";
import { archivo } from "@/components/home/landing-font";
import { LanguageButton, LensHero } from "@/components/home/landing-lens";
import { LandingFooter, LandingMore } from "@/components/home/landing-more";
import { cn } from "@/lib/utils";

import s from "./landing.module.css";

/**
 * The logged-out home page (ADR 0065): a wall of English words under a magnifying lens, then a
 * chat window playing example turns, then what Lingo does. Everything on it is a picture of the
 * app, so the page makes no API calls. The copy is rendered here, on the server; only the lens
 * and the chat window run in the browser.
 */
export async function Landing() {
  const t = await getTranslations("landing");
  const locale = await getLocale();
  const { landing } = await getMessages();

  return (
    <div className={cn(s.page, archivo.variable)}>
      <LensHero meanings={landing.lens.words} hint={t("hint")} next={t("next")}>
        <header className={s.top}>
          <Link href="/" className={cn(s.brand, s.glassChip)}>
            <LogoMark />
            Lingo Agent
          </Link>
          <nav className={s.topActions}>
            <a href={REPO_URL} aria-label="GitHub" className={cn(s.pill, s.iconPill, s.glassChip, s.hideSm)}>
              <GitHubMark className="size-[18px]" />
            </a>
            <LanguageButton
              to={locale === "en" ? "zh-CN" : "en"}
              name={t("switchLanguageName")}
              label={t("switchLanguage")}
              className={cn(s.pill, s.glassChip, s.hideSm)}
            />
            <Link href="/login" className={cn(s.pill, s.glassChip)}>
              {t("login")}
            </Link>
            <Link href="/register" className={cn(s.pill, s.solidPill)}>
              {t("register")}
            </Link>
          </nav>
        </header>

        <div className={s.pitch}>
          <span className={s.eyebrow}>{t("badge")}</span>
          <h1 id="hero-title">{t("title")}</h1>
          <p>{t("subtitle")}</p>
          <div className={s.actions}>
            <Link href="/register" className={s.cta}>
              {t("cta")}
              <ArrowRightIcon className="size-4" />
            </Link>
            <Link href="/login" className={s.pill}>
              {t("login")}
            </Link>
          </div>
        </div>
      </LensHero>
      <main>
        <DemoSection copy={landing.demo} />
        <LandingMore />
      </main>
      <LandingFooter />
    </div>
  );
}
