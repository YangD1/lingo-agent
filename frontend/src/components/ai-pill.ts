// component-spec §6: a bare four-point star in the AI colour, reserved for the AI mark. A plain
// module, not part of the "use client" badge, so the server-rendered landing page can draw a
// static copy.
export const aiMark =
  "inline-flex size-4 shrink-0 items-center justify-center rounded-full text-ai [&_svg]:size-3";

/** Pinned to the top-right corner of a `relative` parent, on a disc of the page colour. */
export const aiMarkCorner = "absolute -top-1.5 -right-1.5 z-1 bg-background";
