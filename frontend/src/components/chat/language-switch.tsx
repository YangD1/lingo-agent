"use client";

import { useTranslations } from "next-intl";
import { useCallback, useEffect, useState } from "react";

import { Segmented } from "@/components/ui/segmented";
import { useErrorMessage } from "@/i18n/errors";
import { ApiError, api } from "@/lib/api";
import type { ChatLanguage, Profile } from "@/lib/types";

const LANGUAGES: ChatLanguage[] = ["zh", "en"];

/**
 * Which language the tutor mainly talks in (ADR 0017 §1): the learner's profile setting,
 * shared by every conversation. Changing it applies from the tutor's next reply.
 */
export function useChatLanguage() {
  const [profile, setProfile] = useState<Profile | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  useEffect(() => {
    api<Profile>("/profile").then(setProfile, () => {});
  }, []);

  const choose = useCallback(
    async (language: ChatLanguage) => {
      if (!profile || profile.chat_language_effective === language) return;
      const before = profile;
      setError(null);
      // Optimistic: the switch moves now, and moves back if saving fails.
      setProfile({ ...profile, chat_language: language, chat_language_effective: language });
      try {
        setProfile(
          await api<Profile>("/profile", { method: "PATCH", json: { chat_language: language } }),
        );
      } catch (e) {
        setProfile(before);
        setError(e instanceof ApiError ? e : new ApiError(0, "network_error", ""));
      }
    },
    [profile],
  );

  return {
    language: profile?.chat_language_effective ?? null,
    /** False while it follows the learner's level (nothing chosen yet). */
    chosen: profile?.chat_language != null,
    choose,
    error,
  };
}

/** "Mostly Chinese | Mostly English", the mode row above the input box. */
export function LanguageSwitch() {
  const t = useTranslations("chat.language");
  const errorMessage = useErrorMessage();
  const { language, chosen, choose, error } = useChatLanguage();
  if (language === null) return null;
  return (
    <div className="flex flex-wrap items-center gap-2 px-1 text-[12.5px] text-muted-foreground">
      <span>{t("label")}</span>
      <Segmented
        size="sm"
        label={t("label")}
        value={language}
        options={LANGUAGES.map((option) => ({ value: option, label: t(option) }))}
        onChange={(option) => void choose(option)}
        data-testid="chat-language"
      />
      <span>{chosen ? t("hint") : t("byLevel")}</span>
      {error && (
        <span role="alert" className="text-destructive">
          {errorMessage(error)}
        </span>
      )}
    </div>
  );
}
