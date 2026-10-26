import type en from "../../../messages/en.json";

/** The demo's copy, `landing.demo` in the message catalogs. */
export type DemoCopy = (typeof en)["landing"]["demo"];

/** The demo's scenes in play order; each names its copy and its tab. */
export const SCENES = ["memory", "practice", "reading", "writing", "deepen"] as const;
