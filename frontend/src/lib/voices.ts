/**
 * Choosing the browser's read-aloud voices (ADR 0018 §1). Browsers often default to their
 * oldest, most robotic voice while better ones sit unused on the same device, so we pick
 * by language, then by what the name says about quality. Pure: the voice list comes in.
 */

/** The fields of `SpeechSynthesisVoice` we look at, so tests can pass plain objects. */
export type VoiceLike = {
  name: string;
  lang: string;
  localService: boolean;
  default: boolean;
  voiceURI: string;
};

export type Accent = "en-US" | "en-GB";
export type Gender = "female" | "male";

/** Lower case with `-`: Android reports `en_US`. */
export const normLang = (lang: string) => lang.toLowerCase().replace(/_/g, "-");

// macOS novelty voices: sound effects, not speech to learn from.
const NOVELTY = new Set(
  [
    "Albert",
    "Bad News",
    "Bahh",
    "Bells",
    "Boing",
    "Bubbles",
    "Cellos",
    "Deranged",
    "Good News",
    "Hysterical",
    "Jester",
    "Organ",
    "Pipe Organ",
    "Superstar",
    "Trinoids",
    "Whisper",
    "Wobble",
    "Zarvox",
  ].map((name) => name.toLowerCase()),
);

// Apple's Eloquence voices and eSpeak: robotic, used only when nothing else is there.
const ROBOTIC = /^(eddy|flo|grandma|grandpa|reed|rocko|sandy|shelley)\b|espeak/i;

// Mandarin; Cantonese is read with other rules, so it doesn't count as Chinese here.
const isMandarin = (lang: string) =>
  (lang.startsWith("zh") || lang.startsWith("cmn")) &&
  !lang.includes("-hk") &&
  !lang.includes("yue") &&
  !lang.includes("-mo");

/** Name without its trailing " (…)", for the novelty list. */
const baseName = (name: string) => name.replace(/\s*\(.*$/, "").trim().toLowerCase();

/**
 * Whether this voice can be offered at all. Edge 150 sometimes lists its online voices as
 * "Microsoft undefined Online (Natural) - undefined" and then reads with the default one.
 */
export function usable(voice: VoiceLike): boolean {
  return !NOVELTY.has(baseName(voice.name)) && !/\bundefined\b/i.test(voice.name);
}

/** Online voices stream from the vendor's servers, which some networks can't reach. */
export const isOnline = (voice: VoiceLike) => !voice.localService;

/** How good the name says the voice is; only compared within one language. */
export function voiceScore(voice: VoiceLike): number {
  const name = voice.name;
  let score = 0;
  if (/natural|neural/i.test(name)) score += 5; // Edge / Windows 11 online voices
  if (/premium/i.test(name)) score += 4; // macOS / iOS downloaded voices
  else if (/enhanced/i.test(name)) score += 3;
  if (/google/i.test(name)) score += 2; // Chrome's online voices
  if (!voice.localService) score += 1;
  if (/multilingual/i.test(name)) score += 1; // one voice for the whole reply
  if (ROBOTIC.test(name)) score -= 5;
  return score;
}

export const isMultilingual = (voice: VoiceLike) => /multilingual/i.test(voice.name);

/** Lower is better: the accent asked for, then any English. Null: not English. */
function englishTier(voice: VoiceLike, accent: Accent): number | null {
  const lang = normLang(voice.lang);
  if (lang === accent.toLowerCase()) return 0;
  return lang === "en" || lang.startsWith("en-") ? 1 : null;
}

/** Lower is better: mainland, then Taiwan, then any Mandarin. Null: not Mandarin. */
function chineseTier(voice: VoiceLike): number | null {
  const lang = normLang(voice.lang);
  if (!isMandarin(lang)) return null;
  if (lang.includes("-cn") || lang.includes("hans")) return 0;
  if (lang.includes("-tw") || lang.includes("hant")) return 1;
  return 2;
}

// Web Speech gives no gender, so we go by the common voices' names (Microsoft, Apple,
// Android). A wrong or missing guess only costs a voice match, never a voice.
const FEMALE = new Set(
  (
    "aria jenny ava emma michelle ana sonia libby maisie zira hazel susan samantha victoria " +
    "allison kate serena karen moira tessa nicky joelle noelle zoe martha catherine " +
    "xiaoxiao xiaoyi xiaohan xiaomo xiaoxuan xiaorui xiaoshuang xiaoyan huihui yaoyao " +
    "hsiaochen hsiaoyu hanhan xiaobei xiaoni tingting meijia lili shanshan yushu flo grandma " +
    "sandy shelley female"
  ).split(" "),
);
const MALE = new Set(
  (
    "guy andrew brian christopher eric roger steffan ryan thomas david mark george alex fred " +
    "tom daniel oliver arthur rishi aaron evan nathan gordon lee " +
    "yunxi yunjian yunyang yunxia yunze yunfeng yunhao kangkang yunjhe zhiwei limu " +
    "eddy grandpa reed rocko male"
  ).split(" "),
);

export function voiceGender(voice: VoiceLike): Gender | null {
  const name = voice.name.toLowerCase();
  // "Ting-Ting", "Li-mu": the hyphen inside a name, not " - English (…)".
  const words = name.replace(/(\w)-(\w)/g, "$1$2").split(/[^\p{L}]+/u);
  // "Male" before the names: "Google UK English Male" also contains "english".
  if (words.includes("male")) return "male";
  if (words.includes("female")) return "female";
  for (const word of words) {
    if (FEMALE.has(word)) return "female";
    if (MALE.has(word)) return "male";
  }
  // Chrome's own voices other than "UK English Male" are female.
  return name.startsWith("google") ? "female" : null;
}

function best<T extends VoiceLike>(
  voices: readonly T[],
  tier: (voice: T) => number | null,
  gender: Gender | null = null,
): T | null {
  let pick: { voice: T; key: number[] } | null = null;
  voices.forEach((voice, index) => {
    const t = tier(voice);
    if (t === null || !usable(voice)) return;
    const mismatch = gender && voiceGender(voice) !== gender ? 1 : 0;
    // Language first, then quality; a matching gender breaks ties, then the browser's order.
    const key = [t, -voiceScore(voice), mismatch, voice.default ? 0 : 1, index];
    if (!pick || compare(key, pick.key) < 0) pick = { voice, key };
  });
  return (pick as { voice: T } | null)?.voice ?? null;
}

function compare(a: number[], b: number[]): number {
  for (let i = 0; i < a.length; i++) if (a[i] !== b[i]) return a[i] - b[i];
  return 0;
}

export type VoiceChoice = {
  /** Chosen by the learner (a `voiceURI`); null or gone from this device: automatic. */
  enVoice?: string | null;
  zhVoice?: string | null;
  accent: Accent;
  /** Voices (`voiceURI`) that made no sound on this page: left out, even if chosen. */
  failed?: ReadonlySet<string>;
};

export type PickedVoices<T extends VoiceLike = VoiceLike> = { en: T | null; zh: T | null };

export function englishVoices<T extends VoiceLike>(voices: readonly T[], accent: Accent): T[] {
  return voices.filter((voice) => usable(voice) && englishTier(voice, accent) !== null);
}

export function chineseVoices<T extends VoiceLike>(voices: readonly T[]): T[] {
  return voices.filter((voice) => usable(voice) && chineseTier(voice) !== null);
}

/**
 * The voices to read English and Chinese with. A multilingual English voice reads the
 * Chinese too, so the reply doesn't switch voices mid-way; otherwise the Chinese voice
 * matches the English one's gender when quality is equal.
 */
export function pickVoices<T extends VoiceLike>(
  all: readonly T[],
  choice: VoiceChoice,
): PickedVoices<T> {
  const failed = choice.failed;
  const voices = failed?.size ? all.filter((voice) => !failed.has(voice.voiceURI)) : all;
  const chosen = (uri: string | null | undefined, allowed: T[]) =>
    uri ? (allowed.find((voice) => voice.voiceURI === uri) ?? null) : null;

  const en =
    chosen(choice.enVoice, englishVoices(voices, choice.accent)) ??
    best(voices, (voice) => englishTier(voice, choice.accent));
  const zhChosen = chosen(choice.zhVoice, chineseVoices(voices));
  if (zhChosen) return { en, zh: zhChosen };
  if (en && isMultilingual(en)) return { en, zh: en };
  return { en, zh: best(voices, chineseTier, en ? voiceGender(en) : null) };
}
