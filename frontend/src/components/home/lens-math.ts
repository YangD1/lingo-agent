/**
 * The geometry behind the home page's word wall and lens (ADR 0065): which words go where,
 * how a point in the hero maps onto the tilted wall and back, and the lens's barrel map.
 * Kept free of the DOM so it can be tested on its own.
 */

/** `ipa: null` marks a common mistake; its meaning (in the messages) is the fix. */
export type WallWord = { word: string; slug: string; ipa: string | null; level: string };

const entry = (word: string, ipa: string | null, level: string): WallWord => ({
  word,
  slug: word.toLowerCase().replace(/[^a-z]+/g, ""),
  ipa,
  level,
});

export const WORDS: WallWord[] = [
  entry("Vocabulary", "/vəˈkæbjələri/", "A2"),
  entry("Grammar", "/ˈɡræmə/", "A1"),
  entry("Pronunciation", "/prəˌnʌnsiˈeɪʃn/", "B1"),
  entry("Thorough", "/ˈθʌrə/", "B2"),
  entry("Although", "/ɔːlˈðəʊ/", "B1"),
  entry("Serendipity", "/ˌserənˈdɪpəti/", "C2"),
  entry("Fluency", "/ˈfluːənsi/", "B2"),
  entry("Collocation", "/ˌkɒləˈkeɪʃn/", "C1"),
  entry("Phrasal Verbs", "/ˈfreɪzl vɜːbz/", "B2"),
  entry("Listening", "/ˈlɪsənɪŋ/", "A1"),
  entry("Idiom", "/ˈɪdiəm/", "B2"),
  entry("Accent", "/ˈæksent/", "B1"),
  entry("Sentence", "/ˈsentəns/", "A1"),
  entry("Tense", "/tens/", "A2"),
  entry("Subjunctive", "/səbˈdʒʌŋktɪv/", "C1"),
  entry("Nuance", "/ˈnjuːɑːns/", "C1"),
  entry("Ubiquitous", "/juːˈbɪkwɪtəs/", "C2"),
  entry("Rhythm", "/ˈrɪðəm/", "B1"),
  entry("Spelling", "/ˈspelɪŋ/", "A2"),
  entry("Synonym", "/ˈsɪnənɪm/", "B2"),
  entry("Conversation", "/ˌkɒnvəˈseɪʃn/", "A2"),
  entry("Meanwhile", "/ˈmiːnwaɪl/", "B1"),
  entry("Resilient", "/rɪˈzɪliənt/", "C1"),
  entry("Article", "/ˈɑːtɪkl/", "A1"),
  entry("Preposition", "/ˌprepəˈzɪʃn/", "A2"),
  entry("Eloquent", "/ˈeləkwənt/", "C1"),
  entry("Curious", "/ˈkjʊəriəs/", "B1"),
  entry("Whisper", "/ˈwɪspə/", "B1"),
  entry("Journey", "/ˈdʒɜːni/", "A2"),
  entry("Schedule", "/ˈʃedjuːl/", "A2"),
  entry("Comfortable", "/ˈkʌmftəbl/", "A2"),
  entry("Wednesday", "/ˈwenzdeɪ/", "A1"),
];

export const MISTAKES: WallWord[] = [
  entry("Informations", null, "✗"),
  entry("Advices", null, "✗"),
  entry("Recieve", null, "✗"),
  entry("Untill", null, "✗"),
  entry("Discuss About", null, "✗"),
];

/** Tilt of the wall, in degrees. */
export const ROTATION = -12;
/** How far the wall slides against the pointer, as a share of the hero. */
export const PAN = 0.18;
/** How far the wheel can drag the wall each way, as a share of the hero's width / height. */
export const WHEEL_X = 0.25;
export const WHEEL_Y = 0.4;
/** Pointer still this long (ms) hands the lens to the idle wander. */
export const IDLE_AFTER = 3500;

/** A small LCG, so the wall looks the same on every load. */
export function rng(seed: number): () => number {
  return () => (seed = (seed * 1664525 + 1013904223) >>> 0) / 4294967296;
}

export type WallStyle = "solid" | "outline" | "thin";
export type WallRow = { thin: boolean; indent: number; words: { word: WallWord; style: WallStyle }[] };

/** Rows of words for a square wall `side` px wide at `fontSize`, about one mistake in nine. */
export function layoutWall(side: number, fontSize: number, seed = 7): WallRow[] {
  const rand = rng(seed);
  const rows = Math.ceil(side / (fontSize * 0.9)) + 1;
  const perRow = Math.ceil(side / (fontSize * 4)) + 3;
  let mistakes = 0;
  return Array.from({ length: rows }, () => {
    const thin = rand() < 0.22;
    const indent = Math.round(-rand() * 4 * fontSize);
    const words = Array.from({ length: perRow }, () => {
      // drawn at random: a fixed slot (n % 9) lined the mistakes up in one column
      const word = rand() < 0.11 ? MISTAKES[mistakes++ % MISTAKES.length] : WORDS[Math.floor(rand() * WORDS.length)];
      const style: WallStyle = thin ? "thin" : rand() < 0.3 ? "outline" : "solid";
      return { word, style };
    });
    return { thin, indent, words };
  });
}

/** Side of a square that, rotated by `rotation`, still covers a `w`×`h` hero at the furthest pan. */
export function coverSide(w: number, h: number, rotation = ROTATION): number {
  const W = w + 2 * w * (PAN + WHEEL_X);
  const H = h + 2 * h * (PAN + WHEEL_Y);
  const a = (rotation * Math.PI) / 180;
  const c = Math.abs(Math.cos(a));
  const s = Math.abs(Math.sin(a));
  return Math.ceil(Math.max(W * c + H * s, W * s + H * c));
}

/** The hero's size, the wall's side and its current offset (pointer parallax + wheel). */
export type Frame = { w: number; h: number; side: number; px: number; py: number; rotation?: number };

/** Hero coordinates to the wall's own, unrotated coordinates. */
export function toLocal(f: Frame, hx: number, hy: number): [number, number] {
  const a = (-(f.rotation ?? ROTATION) * Math.PI) / 180;
  const dx = hx - f.w / 2 - f.px;
  const dy = hy - f.h / 2 - f.py;
  return [dx * Math.cos(a) - dy * Math.sin(a) + f.side / 2, dx * Math.sin(a) + dy * Math.cos(a) + f.side / 2];
}

/** The wall's coordinates back to the hero's. */
export function toHero(f: Frame, lx: number, ly: number): [number, number] {
  const a = ((f.rotation ?? ROTATION) * Math.PI) / 180;
  const dx = lx - f.side / 2;
  const dy = ly - f.side / 2;
  return [dx * Math.cos(a) - dy * Math.sin(a) + f.w / 2 + f.px, dx * Math.sin(a) + dy * Math.cos(a) + f.h / 2 + f.py];
}

export type Box = { l: number; t: number; r: number; b: number };

/** Index of the box containing the point, or -1. */
export function hitBox(boxes: readonly Box[], lx: number, ly: number): number {
  return boxes.findIndex((o) => lx >= o.l && lx <= o.r && ly >= o.t && ly <= o.b);
}

/** Pointer right of centre slides the wall left, so the lens reaches words beyond the edge. */
export function panFor(w: number, h: number, cx: number, cy: number, wx: number, wy: number): [number, number] {
  return [-(cx / w - 0.5) * 2 * PAN * w + wx, -(cy / h - 0.5) * 2 * PAN * h + wy];
}

/** The wheel offset after scrolling by (dx, dy), clamped to the wall's range; `moved` is false at the edge. */
export function wheelStep(
  wx: number,
  wy: number,
  dx: number,
  dy: number,
  w: number,
  h: number,
): { wx: number; wy: number; moved: boolean } {
  const nx = Math.max(-WHEEL_X * w, Math.min(WHEEL_X * w, wx - dx));
  const ny = Math.max(-WHEEL_Y * h, Math.min(WHEEL_Y * h, wy - dy));
  return { wx: nx, wy: ny, moved: nx !== wx || ny !== wy };
}

/** Where the idle lens wanders `seconds` after it took over. */
export function idleTarget(w: number, h: number, seconds: number): [number, number] {
  return [w * (0.55 + 0.28 * Math.sin(seconds * 0.35)), h * (0.45 + 0.22 * Math.sin(seconds * 0.52 + 1))];
}

/**
 * RGBA displacement map for the lens's spherical edge, `n`×`n`: near the rim each pixel samples
 * further out, so the rim squeezes more of the wall into less space, like a glass ball.
 */
export function barrelMap(n: number): Uint8ClampedArray {
  const data = new Uint8ClampedArray(n * n * 4);
  for (let j = 0; j < n; j++) {
    for (let i = 0; i < n; i++) {
      const nx = ((i + 0.5) / n) * 2 - 1;
      const ny = ((j + 0.5) / n) * 2 - 1;
      const d2 = Math.min(1, nx * nx + ny * ny);
      const k = d2 * d2;
      const p = (j * n + i) * 4;
      data[p] = 128 + 127 * nx * k;
      data[p + 1] = 128 + 127 * ny * k;
      data[p + 2] = 128;
      data[p + 3] = 255;
    }
  }
  return data;
}

/**
 * Where the lens starts, so a correction is the first thing seen: on a mistake, with the lens
 * as near (0.58, 0.4) of the hero as it can get. The wall may be pre-scrolled within the wheel's
 * range, and the lens may move off that point as long as it stays whole inside the hero.
 * `still` (reduced motion) leaves out the pointer parallax. Returns the lens point, the pan drawn
 * and the wheel offset; null when no mistake can be brought under a lens.
 */
export function startOnMistake(
  f: Omit<Frame, "px" | "py">,
  boxes: readonly Box[],
  isMistake: (index: number) => boolean,
  radius: number,
  still = false,
): { x: number; y: number; px: number; py: number; wx: number; wy: number } | null {
  const { w, h } = f;
  const target = [w * 0.58, h * 0.4];
  const size = [w, h];
  const range = [WHEEL_X * w, WHEEL_Y * h];
  // the pan drawn for a lens at L is c - k·L + wheel (see panFor), so a word sitting at H
  // unpanned is under the lens when L = H + c - k·L + wheel, i.e. L = (H + c + wheel) / (1 + k)
  const k = still ? 0 : 2 * PAN;
  const c = size.map((n) => (still ? 0 : PAN * n));
  let best: { x: number; y: number; px: number; py: number; wx: number; wy: number } | null = null;
  let bestCost = Infinity;
  boxes.forEach((o, i) => {
    if (!isMistake(i)) return;
    const word = toHero({ ...f, px: 0, py: 0 }, (o.l + o.r) / 2, (o.t + o.b) / 2);
    const wheel = [0, 1].map((a) => {
      const ideal = target[a] * (1 + k) - word[a] - c[a];
      return Math.max(-range[a], Math.min(range[a], ideal));
    });
    const lens = [0, 1].map((a) => (word[a] + c[a] + wheel[a]) / (1 + k));
    if (lens.some((v, a) => v < radius || v > size[a] - radius)) return;
    const cost = Math.hypot(lens[0] - target[0], lens[1] - target[1]) * 4 + Math.hypot(wheel[0], wheel[1]);
    if (cost < bestCost) {
      bestCost = cost;
      const [x, y] = lens;
      best = { x, y, px: x - word[0], py: y - word[1], wx: wheel[0], wy: wheel[1] };
    }
  });
  return best;
}
