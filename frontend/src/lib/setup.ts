/**
 * The setup guide (ADR 0042): five steps, each can be skipped; finishing (or "skip all")
 * marks the account set up, and until then the app sends the learner here.
 */

export const SETUP_STEPS = ["profile", "model", "goals", "tutor", "placement"] as const;
export type SetupStep = (typeof SETUP_STEPS)[number];

/** Where the guide is: one of the steps, or the summary at the end. */
export type SetupView = SetupStep | "done";

export type SetupSteps = Record<SetupStep, boolean>;

export type SetupState = {
  /** Null until the guide is finished once. */
  completed_at: string | null;
  /** Each is true when that step's settings are made, by the guide or elsewhere. */
  steps: SetupSteps;
};

export const SETUP_PATH = "/setup";
/** Where "no chat model yet" leads (the pet's reminder and chat window): the guide's model step. */
export const MODEL_SETUP_PATH = `${SETUP_PATH}?step=model`;

/** `?step=` from a link (e.g. the pet's "set up a model"); anything else starts at the top. */
export function initialView(step: string | undefined): SetupView {
  return (SETUP_STEPS as readonly string[]).includes(step ?? "") ? (step as SetupStep) : "profile";
}

export function nextView(view: SetupView): SetupView {
  if (view === "done") return "done";
  const i = SETUP_STEPS.indexOf(view);
  return SETUP_STEPS[i + 1] ?? "done";
}

export function previousView(view: SetupView): SetupView | null {
  if (view === "done") return SETUP_STEPS[SETUP_STEPS.length - 1];
  const i = SETUP_STEPS.indexOf(view);
  return i > 0 ? SETUP_STEPS[i - 1] : null;
}

/** The step's position, 1-based, for "Step 2 of 5". */
export function stepNumber(step: SetupStep): number {
  return SETUP_STEPS.indexOf(step) + 1;
}

/** The steps left unset, for the summary's "set these up later" list. */
export function unsetSteps(steps: SetupSteps): SetupStep[] {
  return SETUP_STEPS.filter((step) => !steps[step]);
}

/** Where each step's settings live outside the guide, for the summary's links. */
export const STEP_HOMES: Record<SetupStep, string> = {
  profile: "/memory",
  model: "/settings#connections",
  goals: "/memory",
  tutor: "/tutor#looks",
  placement: "/placement",
};
