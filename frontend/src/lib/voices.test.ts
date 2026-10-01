import { describe, expect, it } from "vitest";

import {
  chineseVoices,
  normLang,
  pickVoices,
  usable,
  voiceGender,
  voiceScore,
  type VoiceLike,
} from "@/lib/voices";

/** A voice as a browser lists it; online unless `local`. */
const v = (name: string, lang: string, { local = false, dflt = false } = {}): VoiceLike => ({
  name,
  lang,
  localService: local,
  default: dflt,
  voiceURI: name,
});

// What each platform lists, cut down to the voices that matter here.
const WINDOWS_EDGE = [
  v("Microsoft David - English (United States)", "en-US", { local: true, dflt: true }),
  v("Microsoft Zira - English (United States)", "en-US", { local: true }),
  v("Microsoft Huihui - Chinese (Simplified, PRC)", "zh-CN", { local: true }),
  v("Microsoft Aria Online (Natural) - English (United States)", "en-US"),
  v("Microsoft Guy Online (Natural) - English (United States)", "en-US"),
  v("Microsoft AvaMultilingual Online (Natural) - English (United States)", "en-US"),
  v("Microsoft HiuGaai Online (Natural) - Chinese (Cantonese Traditional)", "zh-HK"),
  v("Microsoft Xiaoxiao Online (Natural) - Chinese (Mainland)", "zh-CN"),
  v("Microsoft Yunxi Online (Natural) - Chinese (Mainland)", "zh-CN"),
  v("Microsoft Ryan Online (Natural) - English (United Kingdom)", "en-GB"),
  v("Microsoft Sonia Online (Natural) - English (United Kingdom)", "en-GB"),
];

const WINDOWS_CHROME = [
  v("Microsoft David - English (United States)", "en-US", { local: true, dflt: true }),
  v("Microsoft Mark - English (United States)", "en-US", { local: true }),
  v("Microsoft Zira - English (United States)", "en-US", { local: true }),
  v("Microsoft Kangkang - Chinese (Simplified, PRC)", "zh-CN", { local: true }),
  v("Microsoft Huihui - Chinese (Simplified, PRC)", "zh-CN", { local: true }),
  v("Google Deutsch", "de-DE"),
  v("Google US English", "en-US"),
  v("Google UK English Female", "en-GB"),
  v("Google UK English Male", "en-GB"),
  v("Google 普通话（中国大陆）", "zh-CN"),
  v("Google 粤語（香港）", "zh-HK"),
  v("Google 國語（臺灣）", "zh-TW"),
];

const MAC_SAFARI = [
  v("Albert", "en-US", { local: true }),
  v("Bad News", "en-US", { local: true }),
  v("Bells", "en-US", { local: true }),
  v("Eddy (English (US))", "en-US", { local: true }),
  v("Fred", "en-US", { local: true }),
  v("Samantha", "en-US", { local: true, dflt: true }),
  v("Ava (Premium)", "en-US", { local: true }),
  v("Daniel", "en-GB", { local: true }),
  v("Sinji", "zh-HK", { local: true }),
  v("Meijia", "zh-TW", { local: true }),
  v("Tingting", "zh-CN", { local: true }),
];

const MAC_CHROME = [...MAC_SAFARI, v("Google US English", "en-US"), v("Google 普通话（中国大陆）", "zh-CN")];

const ANDROID_CHROME = [
  v("English United States", "en_US", { local: true, dflt: true }),
  v("English United Kingdom", "en_GB", { local: true }),
  v("Chinese Hong Kong", "zh_HK", { local: true }),
  v("Chinese Taiwan", "zh_TW", { local: true }),
  v("Chinese China", "zh_CN", { local: true }),
];

const LINUX_ESPEAK = [
  v("eSpeak Cantonese", "yue", { local: true }),
  v("eSpeak English (America)", "en-US", { local: true, dflt: true }),
];

const US = { accent: "en-US" } as const;
const GB = { accent: "en-GB" } as const;
const names = (picked: { en: VoiceLike | null; zh: VoiceLike | null }) => ({
  en: picked.en?.name ?? null,
  zh: picked.zh?.name ?? null,
});

describe("pickVoices", () => {
  it("Windows Edge: a multilingual natural voice reads the whole reply", () => {
    expect(names(pickVoices(WINDOWS_EDGE, US))).toEqual({
      en: "Microsoft AvaMultilingual Online (Natural) - English (United States)",
      zh: "Microsoft AvaMultilingual Online (Natural) - English (United States)",
    });
  });

  it("Windows Edge, British: natural voices, the Chinese one matching the English one's gender", () => {
    expect(names(pickVoices(WINDOWS_EDGE, GB))).toEqual({
      en: "Microsoft Ryan Online (Natural) - English (United Kingdom)",
      zh: "Microsoft Yunxi Online (Natural) - Chinese (Mainland)",
    });
  });

  it("Windows Chrome: Google's online voices over the old local ones", () => {
    expect(names(pickVoices(WINDOWS_CHROME, US))).toEqual({
      en: "Google US English",
      zh: "Google 普通话（中国大陆）",
    });
    expect(pickVoices(WINDOWS_CHROME, GB).en?.name).toBe("Google UK English Female");
  });

  it("macOS: Premium over default, no novelty or Eloquence voices", () => {
    expect(names(pickVoices(MAC_SAFARI, US))).toEqual({ en: "Ava (Premium)", zh: "Tingting" });
    expect(pickVoices(MAC_SAFARI, GB).en?.name).toBe("Daniel");
    expect(pickVoices(MAC_CHROME, US).en?.name).toBe("Ava (Premium)");
  });

  it("macOS without Premium: Samantha, never a sound effect", () => {
    const basic = MAC_SAFARI.filter((voice) => voice.name !== "Ava (Premium)");
    expect(pickVoices(basic, US).en?.name).toBe("Samantha");
  });

  it("Android: reads `en_US`-style tags", () => {
    expect(names(pickVoices(ANDROID_CHROME, US))).toEqual({
      en: "English United States",
      zh: "Chinese China",
    });
  });

  it("Linux with only eSpeak: English, and no Chinese (Cantonese doesn't count)", () => {
    expect(names(pickVoices(LINUX_ESPEAK, US))).toEqual({
      en: "eSpeak English (America)",
      zh: null,
    });
  });

  it("Taiwan Mandarin when there's no mainland voice", () => {
    const noMainland = WINDOWS_CHROME.filter((voice) => normLang(voice.lang) !== "zh-cn");
    expect(pickVoices(noMainland, US).zh?.name).toBe("Google 國語（臺灣）");
  });

  it("keeps the learner's choice, and goes automatic when that voice is gone", () => {
    const choice = {
      ...US,
      enVoice: "Microsoft Zira - English (United States)",
      zhVoice: "Microsoft Huihui - Chinese (Simplified, PRC)",
    };
    expect(names(pickVoices(WINDOWS_EDGE, choice))).toEqual({
      en: "Microsoft Zira - English (United States)",
      zh: "Microsoft Huihui - Chinese (Simplified, PRC)",
    });
    expect(names(pickVoices(WINDOWS_CHROME, { ...US, enVoice: "Ava (Premium)" })).en).toBe(
      "Google US English",
    );
    // A Chinese voice can't be picked for English, nor a Cantonese one for Chinese.
    expect(
      names(
        pickVoices(WINDOWS_CHROME, {
          ...US,
          enVoice: "Google 普通话（中国大陆）",
          zhVoice: "Google 粤語（香港）",
        }),
      ),
    ).toEqual({ en: "Google US English", zh: "Google 普通话（中国大陆）" });
  });

  it("an English voice chosen by hand still lets a chosen Chinese voice read Chinese", () => {
    const choice = {
      ...US,
      enVoice: "Microsoft AvaMultilingual Online (Natural) - English (United States)",
      zhVoice: "Microsoft Xiaoxiao Online (Natural) - Chinese (Mainland)",
    };
    expect(pickVoices(WINDOWS_EDGE, choice).zh?.name).toBe(
      "Microsoft Xiaoxiao Online (Natural) - Chinese (Mainland)",
    );
  });

  it("leaves out voices that made no sound, chosen or not", () => {
    const failed = new Set([
      "Microsoft AvaMultilingual Online (Natural) - English (United States)",
      "Microsoft Aria Online (Natural) - English (United States)",
      "Microsoft Guy Online (Natural) - English (United States)",
      "Microsoft Xiaoxiao Online (Natural) - Chinese (Mainland)",
      "Microsoft Yunxi Online (Natural) - Chinese (Mainland)",
    ]);
    const choice = { ...US, enVoice: "Microsoft Aria Online (Natural) - English (United States)" };
    // Local voices left, all scored alike: the system default first.
    expect(names(pickVoices(WINDOWS_EDGE, { ...choice, failed }))).toEqual({
      en: "Microsoft David - English (United States)",
      zh: "Microsoft Huihui - Chinese (Simplified, PRC)",
    });
  });

  it("nothing to pick from", () => {
    expect(pickVoices([], US)).toEqual({ en: null, zh: null });
  });
});

describe("voiceGender", () => {
  it("goes by common voice names", () => {
    expect(voiceGender(v("Microsoft Guy Online (Natural) - English (United States)", "en-US"))).toBe(
      "male",
    );
    expect(voiceGender(v("Microsoft Xiaoxiao Online (Natural) - Chinese (Mainland)", "zh-CN"))).toBe(
      "female",
    );
    expect(voiceGender(v("Ting-Ting", "zh-CN"))).toBe("female");
    expect(voiceGender(v("Google UK English Male", "en-GB"))).toBe("male");
    expect(voiceGender(v("Google UK English Female", "en-GB"))).toBe("female");
    expect(voiceGender(v("Google US English", "en-US"))).toBe("female");
    expect(voiceGender(v("English United States", "en-US"))).toBeNull();
  });
});

describe("voiceScore and usable", () => {
  it("ranks natural over premium over Google over plain, robotic last", () => {
    const natural = voiceScore(v("Microsoft Aria Online (Natural) - English (United States)", "en-US"));
    const premium = voiceScore(v("Ava (Premium)", "en-US", { local: true }));
    const google = voiceScore(v("Google US English", "en-US"));
    const plain = voiceScore(v("Samantha", "en-US", { local: true }));
    const robotic = voiceScore(v("Eddy (English (US))", "en-US", { local: true }));
    expect([natural, premium, google, plain, robotic]).toEqual(
      [natural, premium, google, plain, robotic].sort((a, b) => b - a),
    );
    expect(new Set([natural, premium, google, plain, robotic]).size).toBe(5);
  });

  it("drops novelty voices and Cantonese from the lists", () => {
    expect(usable(v("Bad News", "en-US"))).toBe(false);
    expect(usable(v("Whisper", "en-US"))).toBe(false);
    expect(usable(v("Samantha", "en-US"))).toBe(true);
    // Edge 150 sometimes lists every online voice like this, then reads with the default.
    expect(usable(v("Microsoft undefined Online (Natural) - undefined", "en-US"))).toBe(false);
    expect(chineseVoices(WINDOWS_CHROME).map((voice) => voice.name)).toEqual([
      "Microsoft Kangkang - Chinese (Simplified, PRC)",
      "Microsoft Huihui - Chinese (Simplified, PRC)",
      "Google 普通话（中国大陆）",
      "Google 國語（臺灣）",
    ]);
  });
});
