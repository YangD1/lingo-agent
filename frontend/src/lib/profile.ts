import type { Profile } from "@/lib/types";

/** The learner-editable profile fields (cefr_level comes from assessment, ADR 0010). */
export const PROFILE_FIELDS = [
  "native_language",
  "occupation",
  "goal",
  "target_exam",
  "interests",
  "daily_minutes",
  "explanation_language",
  "timezone",
] as const;
export type ProfileField = (typeof PROFILE_FIELDS)[number];

/** What the form holds: every field as the text of its input ("" = not set). */
export type ProfileForm = Record<ProfileField, string>;

export type ProfilePatch = Partial<{
  [K in ProfileField]: Profile[K];
}>;

/** Interests are typed as one line, separated by commas (either width) or 、. */
export function parseInterests(text: string): string[] {
  const items = text
    .split(/[,，、]/)
    .map((s) => s.trim())
    .filter(Boolean);
  return [...new Set(items)];
}

export function toForm(profile: Profile): ProfileForm {
  return {
    native_language: profile.native_language ?? "",
    occupation: profile.occupation ?? "",
    goal: profile.goal ?? "",
    target_exam: profile.target_exam ?? "",
    interests: profile.interests.join(", "),
    daily_minutes: profile.daily_minutes?.toString() ?? "",
    explanation_language: profile.explanation_language ?? "",
    timezone: profile.timezone ?? "",
  };
}

function parse(field: ProfileField, text: string): ProfilePatch[ProfileField] {
  const value = text.trim();
  switch (field) {
    case "interests":
      return parseInterests(value);
    case "daily_minutes":
      return value ? Number(value) : null;
    default:
      return (value || null) as ProfilePatch[ProfileField];
  }
}

/**
 * Only the fields the learner changed: the backend marks every field it receives as set
 * by hand, and reflection never overwrites those (ADR 0009), so untouched fields must not
 * be sent.
 */
export function profileChanges(saved: Profile, form: ProfileForm): ProfilePatch {
  const changes: Record<string, unknown> = {};
  for (const field of PROFILE_FIELDS) {
    const value = parse(field, form[field]);
    const before = saved[field];
    const same = Array.isArray(value)
      ? JSON.stringify(value) === JSON.stringify(before)
      : value === before;
    if (!same) changes[field] = value;
  }
  return changes as ProfilePatch;
}
