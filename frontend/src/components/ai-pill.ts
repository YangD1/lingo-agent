// component-spec §6: a 16px pill in the AI colour, reserved for the AI badge. A plain module,
// not part of the "use client" badge, so the server-rendered landing page can draw a static copy.
export const aiPill =
  "inline-flex h-4 shrink-0 items-center gap-0.5 rounded-full border border-ai/22 bg-[color-mix(in_oklab,var(--ai)_11%,var(--card))] pr-[5px] pl-1 text-[10px] leading-none font-semibold text-ai";
