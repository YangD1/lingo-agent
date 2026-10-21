/**
 * Which text font this browser uses (ADR 0060). Each choice but `system` has its own
 * public/fonts/<choice>/font.css, sliced by unicode-range, linked only when chosen; the
 * stacks themselves live in globals.css under `:root[data-font=…]`.
 */
export const FONT_CHOICES = ["sans", "wenkai", "serif", "system"] as const;
export type FontChoice = (typeof FONT_CHOICES)[number];

export const DEFAULT_FONT: FontChoice = "sans";
export const FONT_KEY = "lingo.font";

/** What is stored, or the default for anything missing or unknown. */
export function parseFontChoice(raw: string | null): FontChoice {
  return FONT_CHOICES.find((c) => c === raw) ?? DEFAULT_FONT;
}

export function fontCssHref(choice: FontChoice): string | null {
  return choice === "system" ? null : `/fonts/${choice}/font.css`;
}

/** Links the choice's stylesheet once; its font files load only where text uses them. */
export function ensureFontCss(choice: FontChoice): void {
  const href = fontCssHref(choice);
  if (!href || document.querySelector(`link[data-font-css="${choice}"]`)) return;
  const link = document.createElement("link");
  link.rel = "stylesheet";
  link.href = href;
  link.dataset.fontCss = choice;
  document.head.appendChild(link);
}

export function applyFont(choice: FontChoice): void {
  ensureFontCss(choice);
  document.documentElement.dataset.font = choice;
}

/**
 * Runs in <head> before the first paint, so the page never shows the default font and
 * then swaps. Self-contained: it cannot import, so the pieces above are inlined.
 */
export const FONT_BOOT_SCRIPT = `(function(){var c=${JSON.stringify(DEFAULT_FONT)};try{var s=localStorage.getItem(${JSON.stringify(FONT_KEY)});if(${JSON.stringify(FONT_CHOICES)}.indexOf(s)>=0)c=s}catch(e){}document.documentElement.dataset.font=c;if(c!=="system"){var l=document.createElement("link");l.rel="stylesheet";l.href="/fonts/"+c+"/font.css";l.dataset.fontCss=c;document.head.appendChild(l)}})()`;
