"use client";

import { Play } from "lucide-react";
import { useTranslations } from "next-intl";
import { useId } from "react";

import { Button } from "@/components/ui/button";
import { NativeSelect } from "@/components/ui/native-select";
import {
  EN_RATE_MAX,
  EN_RATE_MIN,
  speakSample,
  useCanSpeak,
  useFailedVoices,
  useSpeechSettings,
  useVoices,
} from "@/lib/speech";
import { chineseVoices, englishVoices, pickVoices, type Accent } from "@/lib/voices";

const ACCENTS: Accent[] = ["en-US", "en-GB"];

/**
 * Voices, accent and speed for reading aloud (ADR 0018 §2). Kept in this browser: the
 * voices are the device's own. Shared by the settings page and the reply's gear button.
 */
export function SpeechSettings() {
  const t = useTranslations("speech");
  const id = useId();
  const speakable = useCanSpeak();
  const voices = useVoices();
  const [settings, update] = useSpeechSettings();
  const failed = useFailedVoices();

  if (!speakable) return <p className="text-sm text-muted-foreground">{t("unsupported")}</p>;

  // What "automatic" would pick for each, given the other one as it's set now.
  const autoEn = pickVoices(voices, { ...settings, enVoice: null, failed }).en;
  const autoZh = pickVoices(voices, { ...settings, zhVoice: null, failed }).zh;
  const label = (name: string, uri: string) => (failed.has(uri) ? t("silent", { name }) : name);
  const noChinese = voices.length > 0 && !autoZh;
  const english = englishVoices(voices, settings.accent);
  const chinese = chineseVoices(voices);
  const auto = (name: string | undefined) => (name ? t("auto", { name }) : t("autoNone"));

  return (
    <div className="flex flex-col gap-3 text-sm" data-testid="speech-settings">
      <fieldset className="flex flex-col gap-1">
        <legend className="mb-1 font-medium">{t("accent")}</legend>
        <div className="flex gap-4">
          {ACCENTS.map((accent) => (
            <label key={accent} className="flex items-center gap-1.5">
              <input
                type="radio"
                name={`${id}-accent`}
                className="size-4 accent-primary"
                checked={settings.accent === accent}
                onChange={() => update({ accent })}
              />
              {t(accent === "en-US" ? "accentUS" : "accentGB")}
            </label>
          ))}
        </div>
      </fieldset>

      <div className="flex flex-col gap-1">
        <label htmlFor={`${id}-en`} className="font-medium">
          {t("enVoice")}
        </label>
        <div className="flex items-center gap-1">
          <NativeSelect
            id={`${id}-en`}
            className="min-w-0 flex-1"
            value={settings.enVoice ?? ""}
            disabled={voices.length === 0}
            onChange={(e) => update({ enVoice: e.target.value || null })}
          >
            <option value="">{auto(autoEn?.name)}</option>
            {english.map((voice) => (
              <option key={voice.voiceURI} value={voice.voiceURI}>
                {label(voice.name, voice.voiceURI)}
              </option>
            ))}
          </NativeSelect>
          <Button size="sm" variant="outline" onClick={() => speakSample("en-US")}>
            <Play />
            {t("try")}
          </Button>
        </div>
      </div>

      <div className="flex flex-col gap-1">
        <label htmlFor={`${id}-zh`} className="font-medium">
          {t("zhVoice")}
        </label>
        <div className="flex items-center gap-1">
          <NativeSelect
            id={`${id}-zh`}
            className="min-w-0 flex-1"
            value={settings.zhVoice ?? ""}
            disabled={chinese.length === 0}
            onChange={(e) => update({ zhVoice: e.target.value || null })}
          >
            <option value="">{auto(autoZh?.name)}</option>
            {chinese.map((voice) => (
              <option key={voice.voiceURI} value={voice.voiceURI}>
                {label(voice.name, voice.voiceURI)}
              </option>
            ))}
          </NativeSelect>
          <Button
            size="sm"
            variant="outline"
            disabled={noChinese}
            onClick={() => speakSample("zh-CN")}
          >
            <Play />
            {t("try")}
          </Button>
        </div>
        {noChinese && (
          <p className="text-muted-foreground">{t("noChinese")}</p>
        )}
      </div>

      <div className="flex flex-col gap-1">
        <label htmlFor={`${id}-rate`} className="flex justify-between font-medium">
          {t("rate")}
          <span className="font-normal text-muted-foreground tabular-nums">
            {t("rateValue", { rate: settings.enRate.toFixed(1) })}
          </span>
        </label>
        <input
          id={`${id}-rate`}
          type="range"
          min={EN_RATE_MIN}
          max={EN_RATE_MAX}
          step={0.1}
          className="accent-primary"
          value={settings.enRate}
          onChange={(e) => update({ enRate: Number(e.target.value) })}
        />
      </div>

      <p className="text-xs text-muted-foreground">
        {voices.length === 0 ? t("noVoices") : t("hint")}
      </p>
      {failed.size > 0 && (
        <p className="text-xs text-muted-foreground" data-testid="silent-voices">
          {t("silentHint")}
        </p>
      )}
    </div>
  );
}
