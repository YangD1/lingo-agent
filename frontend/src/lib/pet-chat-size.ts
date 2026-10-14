/**
 * The desk pet's chat window size on wide screens (task 77, Q77a/b): the learner drags its
 * far edge, top edge or the corner between them; the side by the pet and the bottom stay
 * put. A size they chose is kept in this browser; none means the default.
 */

export type ChatSize = { width: number; height: number };
export type Viewport = { width: number; height: number };

/** 28rem × 44rem, lower on short screens. */
export const DEFAULT_CHAT_SIZE: ChatSize = { width: 448, height: 704 };
/** 20rem × 24rem: the shortcuts, a message or two and the input box still fit. */
export const MIN_CHAT_SIZE: ChatSize = { width: 320, height: 384 };
/** The room the window leaves: the pet's side (`md:right-28`) plus a gutter on the other,
 * and 1rem above and below. */
const SIDE_ROOM = 112 + 16;
const TOP_ROOM = 32;

/** `size` fitted to the viewport: no smaller than the minimum unless the screen is. */
export function fitChatSize(size: ChatSize, viewport: Viewport): ChatSize {
  const fit = (value: number, min: number, max: number) =>
    Math.round(Math.min(Math.max(value, min), Math.max(max, 0)));
  return {
    width: fit(size.width, MIN_CHAT_SIZE.width, viewport.width - SIDE_ROOM),
    height: fit(size.height, MIN_CHAT_SIZE.height, viewport.height - TOP_ROOM),
  };
}

const SIZE_KEY = "lingo.tutorPet.chatSize";

/** The size the learner chose, or null for the default. */
export function readChatSize(): ChatSize | null {
  try {
    const found = JSON.parse(window.localStorage.getItem(SIZE_KEY) ?? "null") as Partial<ChatSize> | null;
    const width = Number(found?.width);
    const height = Number(found?.height);
    return width > 0 && height > 0 ? { width, height } : null;
  } catch {
    return null; // the default, which is fine
  }
}

/** Keeps `size` for next time; null goes back to the default. */
export function keepChatSize(size: ChatSize | null) {
  try {
    if (size) window.localStorage.setItem(SIZE_KEY, JSON.stringify(size));
    else window.localStorage.removeItem(SIZE_KEY);
  } catch {
    // Not kept: the window opens at the default next time.
  }
}
