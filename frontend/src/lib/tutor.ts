import { useSyncExternalStore } from "react";

import { OUTFITS, type Outfit } from "@/components/tutor/avatar-draw";
import { api } from "@/lib/api";
import { VOICE_LANGUAGES, type VoiceLanguage, type VoiceOption } from "@/lib/types";

/** A saved choice that isn't applied now: its model can't be used any more (ADR 0032 §3). */
export type TutorChoice = "chat_model" | "voices" | "realtime_model";

/** The learner's tutor (backend app/api/tutor.py): null fields follow the settings page. */
export type Tutor = {
  name: string | null;
  avatar: Outfit | null;
  /** The fur, `#rrggbb`. */
  color: string | null;
  animate: boolean;
  /** The desk pet in the corner (ADR 0032 §4a). */
  pet: boolean;
  /** The pet's own reminders in a bubble (ADR 0039 §4). */
  nudges: boolean;
  /** The tutor speaks first the first time the pet is opened in a day (ADR 0041). */
  daily_opening: boolean;
  /** `<connection>:<model>`. */
  chat_model: string | null;
  /** The read-aloud model `voices` were picked for. */
  tts_model: string | null;
  voices: Partial<Record<VoiceLanguage, string>>;
  realtime_model: string | null;
  realtime_voice: string | null;
  display_name: string;
  display_avatar: Outfit;
  unavailable: TutorChoice[];
};

export const DEFAULT_TUTOR: Tutor = {
  name: null,
  avatar: null,
  color: null,
  animate: true,
  pet: true,
  nudges: true,
  daily_opening: true,
  chat_model: null,
  tts_model: null,
  voices: {},
  realtime_model: null,
  realtime_voice: null,
  display_name: "JOJO",
  display_avatar: "cat",
  unavailable: [],
};

/** A chain serving the learner now: its models in route order, the first in use. */
export type TutorChain = {
  models: string[];
  /** The main account's name when its connections serve this for a member (ADR 0031 §5). */
  provided_by: string | null;
  quota_exhausted: boolean;
};

export type TutorOptions = {
  chat: TutorChain;
  read_aloud: TutorChain & {
    /** The model voices are picked for; null: no server read-aloud. */
    voice_model: string | null;
    /** Its catalog; empty: voices are typed in. */
    voice_options: VoiceOption[];
    /** What it reads each language with now. */
    default_voices: Partial<Record<VoiceLanguage, string | null>>;
  };
  realtime: TutorChain & {
    voice_options: Record<string, VoiceOption[]>;
    default_voices: Record<string, string | null>;
  };
};

/** What the page edits: "" follows the default. */
export type TutorForm = {
  name: string;
  avatar: Outfit;
  color: string;
  animate: boolean;
  pet: boolean;
  nudges: boolean;
  daily_opening: boolean;
  chat_model: string;
  voices: Record<VoiceLanguage, string>;
  realtime_model: string;
  realtime_voice: string;
};

export type TutorBody = Omit<Tutor, "display_name" | "display_avatar" | "unavailable">;

/**
 * The form for `tutor`. Choices not applied now are left out: saving them again would be
 * refused, and the page says they were dropped.
 */
export function toForm(tutor: Tutor, options: TutorOptions): TutorForm {
  const off = new Set(tutor.unavailable);
  const voicesHold = !off.has("voices") && tutor.tts_model === options.read_aloud.voice_model;
  const realtimeHolds = !off.has("realtime_model");
  return {
    name: tutor.name ?? "",
    avatar: tutor.avatar && OUTFITS.includes(tutor.avatar) ? tutor.avatar : "cat",
    color: tutor.color ?? "",
    animate: tutor.animate,
    pet: tutor.pet,
    nudges: tutor.nudges,
    daily_opening: tutor.daily_opening,
    chat_model: off.has("chat_model") ? "" : (tutor.chat_model ?? ""),
    voices: Object.fromEntries(
      VOICE_LANGUAGES.map((lang) => [lang, voicesHold ? (tutor.voices[lang] ?? "") : ""]),
    ) as Record<VoiceLanguage, string>,
    realtime_model: realtimeHolds ? (tutor.realtime_model ?? "") : "",
    realtime_voice: realtimeHolds ? (tutor.realtime_voice ?? "") : "",
  };
}

/** What `PUT /tutor` takes for `form`. */
export function toBody(form: TutorForm, options: TutorOptions): TutorBody {
  const voices = Object.fromEntries(
    VOICE_LANGUAGES.flatMap((lang) => {
      const voice = form.voices[lang].trim();
      return voice ? [[lang, voice]] : [];
    }),
  ) as Partial<Record<VoiceLanguage, string>>;
  const picked = Object.keys(voices).length > 0;
  return {
    name: form.name.trim() || null,
    avatar: form.avatar,
    color: form.color || null,
    animate: form.animate,
    pet: form.pet,
    nudges: form.nudges,
    daily_opening: form.daily_opening,
    chat_model: form.chat_model || null,
    tts_model: picked ? options.read_aloud.voice_model : null,
    voices,
    realtime_model: form.realtime_model || null,
    realtime_voice: (form.realtime_model && form.realtime_voice.trim()) || null,
  };
}

/** Whether `form` differs from what is saved. */
export function formChanged(saved: Tutor, form: TutorForm, options: TutorOptions): boolean {
  return (
    JSON.stringify(toBody(toForm(saved, options), options)) !==
    JSON.stringify(toBody(form, options))
  );
}

/** `<connection>:<model>` split at the first colon (model ids may hold more). */
export function splitRef(ref: string): { connection: string; model: string } {
  const at = ref.indexOf(":");
  return at < 0
    ? { connection: "", model: ref }
    : { connection: ref.slice(0, at), model: ref.slice(at + 1) };
}

/** The voices `options` offer for `lang`, those of that very accent first. */
export function voicesFor(options: VoiceOption[], lang: VoiceLanguage): VoiceOption[] {
  return options
    .filter((o) => o.languages.includes(lang))
    .sort((a, b) => Number(b.accent === lang) - Number(a.accent === lang));
}

/** What the tutor says when a voice is tried, in that voice's language. */
export function voiceSample(lang: VoiceLanguage, name: string): string {
  return lang === "zh-CN"
    ? `你好，我是${name}。我们一起练英语吧！`
    : `Hi, I'm ${name}. Let's practise some English together!`;
}

// The saved tutor, shared by the tutor page and the desk pet: saving updates both.
let current: Tutor | null = null;
let loading: Promise<Tutor> | null = null;
const listeners = new Set<() => void>();

export function setTutor(tutor: Tutor) {
  current = tutor;
  listeners.forEach((listener) => listener());
}

/** The saved tutor, fetched once per page; a failed fetch is tried again next time. */
export function loadTutor(): Promise<Tutor> {
  loading ??= api<Tutor>("/tutor").then(
    (tutor) => {
      setTutor(tutor);
      return tutor;
    },
    (error: unknown) => {
      loading = null;
      throw error;
    },
  );
  return loading;
}

/** Forgets the saved tutor (tests). */
export function resetTutorCache() {
  current = null;
  loading = null;
}

/** The saved tutor; null until fetched (or when it can't be). */
export function useTutor(): Tutor | null {
  return useSyncExternalStore(
    (listener) => {
      listeners.add(listener);
      loadTutor().catch(() => {});
      return () => listeners.delete(listener);
    },
    () => current,
    () => null,
  );
}
