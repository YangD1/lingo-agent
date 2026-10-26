import { ArrowRightIcon } from "lucide-react";
import { getLocale, getTranslations } from "next-intl/server";
import Link from "next/link";
import type { CSSProperties, ReactNode } from "react";

import { LanguageButton } from "@/components/home/landing-lens";
import { RiseIn } from "@/components/home/landing-rise";
import { cn } from "@/lib/utils";

import s from "./landing.module.css";
import m from "./landing-more.module.css";

const REPO_URL = "https://github.com/YangD1/lingo-agent";

/** `--v` / `--h` are read by the bar and wave CSS. */
const v = (value: string) => ({ "--v": value }) as CSSProperties;
const h = (value: string) => ({ "--h": value }) as CSSProperties;
const WAVE = ["30%", "70%", "45%", "90%", "60%", "35%", "80%", "50%", "25%", "65%", "40%", "75%"];
const PROVIDERS = ["DeepSeek", "OpenAI", "Anthropic", "Qwen", "SiliconFlow", "Ollama"];
const PLAN = ["review", "learn", "practice", "reading"] as const;
const TRUST = ["activity", "usage", "confirm", "background"] as const;

const rich = { b: (c: ReactNode) => <b>{c}</b>, s: (c: ReactNode) => <s>{c}</s> };

function Card({
  wide,
  warm,
  picture,
  title,
  body,
}: {
  wide?: 3 | 4 | 6;
  warm?: boolean;
  picture: ReactNode;
  title: string;
  body: string;
}) {
  return (
    <li className={cn(m.card, wide && m[`w${wide}`], warm && m.warm)} data-rise>
      {picture}
      <div>
        <h4>{title}</h4>
        <p>{body}</p>
      </div>
    </li>
  );
}

function Still({ children }: { children: ReactNode }) {
  return (
    <div className={m.still} aria-hidden>
      {children}
    </div>
  );
}

function Bar({ label, value, width }: { label: string; value: string; width: string }) {
  return (
    <div className={m.bar}>
      <span>{label}</span>
      <span>{value}</span>
      <i style={v(width)} />
    </div>
  );
}

/**
 * Screen three onward (ADR 0065 §3): what Lingo does, the transparency band, self-hosting and a
 * closing call to action. Static pictures of the app; the cards fade in as they enter (RiseIn).
 */
export async function LandingMore() {
  const t = await getTranslations("landing");

  return (
    <RiseIn className={m.more}>
      <header className={m.moreHead} data-rise>
        <span className={m.kicker}>{t("more.kicker")}</span>
        <h2>{t("more.title")}</h2>
        <p>{t("more.body")}</p>
      </header>

      <section className={m.group} aria-labelledby="g-learn">
        <h3 id="g-learn" data-rise>
          {t("learn.title")} <small>{t("learn.sub")}</small>
        </h3>
        <ul className={m.bento}>
          <Card
            wide={4}
            warm
            title={t("learn.memory.title")}
            body={t("learn.memory.body")}
            picture={
              <Still>
                <span className={m.chip}>{t("learn.memory.chip")}</span>
                <div className={cn(m.bubble, m.me)} lang="en">
                  Last weekend I go hiking with my friends.
                </div>
                <div className={cn(m.bubble, m.fix)}>{t.rich("learn.memory.fix", rich)}</div>
                <span className={cn(m.chip, m.ai)}>{t("learn.memory.activity")}</span>
              </Still>
            }
          />
          <Card
            title={t("learn.grammar.title")}
            body={t("learn.grammar.body")}
            picture={
              <Still>
                <Bar label={t("learn.grammar.pastSimple")} value="92%" width="92%" />
                <Bar label={t("learn.grammar.articles")} value="64%" width="64%" />
                <Bar label={t("learn.grammar.presentPerfect")} value="41%" width="41%" />
              </Still>
            }
          />
          <Card
            title={t("learn.vocab.title")}
            body={t("learn.vocab.body")}
            picture={
              <Still>
                <div className={m.flash}>
                  <strong lang="en">Thorough</strong>
                  <em>{t("learn.vocab.meaning")}</em>
                </div>
                <div className={m.rates}>
                  <span>{t("learn.vocab.again")}</span>
                  <span>{t("learn.vocab.hard")}</span>
                  <span className={m.on}>{t("learn.vocab.good")}</span>
                  <span>{t("learn.vocab.easy")}</span>
                </div>
              </Still>
            }
          />
          <Card
            title={t("learn.placement.title")}
            body={t("learn.placement.body")}
            picture={
              <Still>
                <div className={m.big}>
                  B1<small>{t("learn.placement.vocab")}</small>
                </div>
              </Still>
            }
          />
          <Card
            title={t("learn.speaking.title")}
            body={t("learn.speaking.body")}
            picture={
              <Still>
                <div className={m.wave}>
                  {WAVE.map((x, i) => (
                    <i key={i} style={h(x)} />
                  ))}
                </div>
                <span className={m.chip}>{t("learn.speaking.chip")}</span>
              </Still>
            }
          />
          <Card
            wide={3}
            title={t("learn.reading.title")}
            body={t("learn.reading.body")}
            picture={
              <Still>
                <p className={m.read} lang="en">
                  Scientists <mark>discovered</mark> a new planet that may have water. It is <u>orbiting</u> a
                  small star about 40 light-years away.
                </p>
                <span className={m.chip}>{t("learn.reading.chip")}</span>
              </Still>
            }
          />
          <Card
            wide={3}
            title={t("learn.writing.title")}
            body={t("learn.writing.body")}
            picture={
              <Still>
                <div className={cn(m.bubble, m.fix)} lang="en">
                  I have lived here <s>since three years</s> → <b>for three years</b>.
                </div>
                <Bar label={t("learn.writing.bar")} value="7.5 / 9" width="83%" />
              </Still>
            }
          />
          <Card
            wide={6}
            title={t("learn.plan.title")}
            body={t("learn.plan.body")}
            picture={
              <ul className={m.plan} aria-hidden>
                {PLAN.map((k, i) => (
                  <li key={k} className={cn(i === 0 && m.done)}>
                    {t(`learn.plan.${k}.task`)}
                    <span>{t(`learn.plan.${k}.time`)}</span>
                  </li>
                ))}
              </ul>
            }
          />
        </ul>
      </section>

      <section className={m.band} aria-labelledby="g-trust" data-rise>
        <h3 id="g-trust">{t("trust.title")}</h3>
        <ul>
          {TRUST.map((k) => (
            <li key={k}>
              <b>{t(`trust.${k}.title`)}</b>
              <span>{t(`trust.${k}.body`)}</span>
            </li>
          ))}
        </ul>
      </section>

      <section className={m.group} aria-labelledby="g-platform">
        <h3 id="g-platform" data-rise>
          {t("platform.title")} <small>{t("platform.sub")}</small>
        </h3>
        <ul className={m.bento}>
          <Card
            title={t("platform.models.title")}
            body={t("platform.models.body")}
            picture={
              <Still>
                <div className={m.providers}>
                  {PROVIDERS.map((p) => (
                    <span key={p}>{p}</span>
                  ))}
                </div>
              </Still>
            }
          />
          <Card
            title={t("platform.server.title")}
            body={t("platform.server.body")}
            picture={
              <Still>
                <div className={m.big}>
                  1.7<small>{t("platform.server.unit")}</small>
                </div>
              </Still>
            }
          />
          <Card
            title={t("platform.share.title")}
            body={t("platform.share.body")}
            picture={
              <Still>
                <span className={m.chip}>{t("platform.share.invite")}</span>
                <span className={m.chip}>{t("platform.share.allowance")}</span>
              </Still>
            }
          />
        </ul>
      </section>

      <section className={m.closing} data-rise>
        <h2>{t("closing.title")}</h2>
        <p>{t("closing.sub")}</p>
        <Link href="/register" className={s.cta}>
          {t("cta")}
          <ArrowRightIcon className="size-4" />
        </Link>
      </section>
    </RiseIn>
  );
}

/** The footer, with the language button the top bar hides on phones. */
export async function LandingFooter() {
  const t = await getTranslations("landing");
  const locale = await getLocale();

  return (
    <footer className={m.foot}>
      <div>
        <span>{t("footer.tagline")}</span>
        <a href={REPO_URL}>{t("footer.github")}</a>
        <a href={t("footer.docsUrl")}>{t("footer.docs")}</a>
        <LanguageButton
          to={locale === "en" ? "zh-CN" : "en"}
          name={t("switchLanguageName")}
          label={t("switchLanguage")}
          className={m.footLang}
        />
      </div>
    </footer>
  );
}
