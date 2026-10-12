/**
 * Draws the tutor cat (ADR 0032 §4): one cat, front on, in a 100×100 box, with an outfit
 * layered on top. The fur is the learner's color; shade, light and eye colors come from it,
 * outfits keep their own. Decorations (dots, waves, the speaker mark) use `ink`, the
 * element's text color, so they suit the theme.
 */

import type { Pose } from "./avatar-state";

/** The outfits; ids are the backend's `TUTOR_AVATARS`. `cat` wears nothing (the logo cat). */
export const OUTFITS = ["cat", "classic", "casual", "sporty", "artsy"] as const;
export type Outfit = (typeof OUTFITS)[number];

/** The logo's orange: the fur when the learner hasn't picked one. */
export const DEFAULT_FUR = "#f25c3b";

/** Furs offered to pick from (any `#rrggbb` is drawn). */
export const FUR_SWATCHES = [
  "#f25c3b", // logo orange
  "#f2a03b", // ginger
  "#c9a27e", // milk tea
  "#8a8f98", // grey
  "#6c8ebf", // blue grey
  "#2e2b2b", // black
  "#f4f1ec", // white
  "#f2a7b8", // pink
] as const;

export type Palette = {
  fur: string;
  shade: string;
  light: string;
  innerEar: string;
  /** Eyes and the open mouth. */
  eye: string;
  /** The glint in the eyes. */
  glint: string;
  /** Outline for a fur too pale to stand out on a light page; null otherwise. */
  edge: string | null;
};

type Rgb = [number, number, number];

function parseHex(hex: string): Rgb | null {
  const match = /^#?([0-9a-f]{6})$/i.exec(hex.trim());
  if (!match) return null;
  const n = parseInt(match[1], 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}

const toHex = (rgb: Rgb) =>
  `#${rgb.map((c) => Math.round(Math.min(255, Math.max(0, c))).toString(16).padStart(2, "0")).join("")}`;

const mix = (a: Rgb, b: Rgb, t: number): Rgb => [0, 1, 2].map((i) => a[i] + (b[i] - a[i]) * t) as Rgb;

/** Relative luminance (WCAG), 0 black .. 1 white. */
export function luminance([r, g, b]: Rgb): number {
  const lin = (c: number) => {
    const s = c / 255;
    return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
  };
  return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b);
}

const BLACK: Rgb = [0, 0, 0];
const WHITE: Rgb = [255, 255, 255];
const PINK: Rgb = [244, 150, 160];

/** The colors for a cat of `fur` (`#rrggbb`; anything else gives the default). */
export function paletteFor(fur: string | null | undefined): Palette {
  const base = parseHex(fur ?? "") ?? parseHex(DEFAULT_FUR)!;
  const lum = luminance(base);
  const dark = lum < 0.06;
  return {
    fur: toHex(base),
    shade: toHex(dark ? mix(base, WHITE, 0.12) : mix(base, BLACK, 0.18)),
    light: toHex(mix(base, WHITE, dark ? 0.25 : 0.55)),
    innerEar: toHex(mix(base, PINK, 0.55)),
    // A dark cat gets the black cat's yellow eyes, so they still show.
    eye: dark ? "#f2c94c" : "#2b2321",
    glint: dark ? "#2b2321" : "#ffffff",
    edge: lum > 0.75 ? toHex(mix(base, BLACK, 0.25)) : null,
  };
}

export type DrawOptions = {
  outfit: Outfit;
  palette: Palette;
  /** The text color around the avatar, for decorations. */
  ink: string;
  /** Leave out the small things (whiskers, pencil, dots, waves) that blur at avatar size. */
  small: boolean;
  /** Mark it as talking with a still speaker sign (when nothing may move). */
  speakerMark: boolean;
};

type Ctx = CanvasRenderingContext2D;

// Where things are in the 100×100 box.
const NECK = { x: 50, y: 74 };
const HEAD = { x: 50, y: 47, rx: 29, ry: 25 };
const EYE_X = 11;
const EYE_Y = 48;

const SPARK = "M0 -7Q0 0 7 0Q0 0 0 7Q0 0 -7 0Q0 0 0 -7Z";

/** Draws one frame of the cat at `pose` into a 100×100 box (scale the context first). */
export function drawAvatar(ctx: Ctx, pose: Pose, options: DrawOptions) {
  const { outfit, palette: p, small } = options;
  ctx.clearRect(0, 0, 100, 100);
  ctx.lineCap = "round";
  ctx.lineJoin = "round";
  const breath = Math.sin((pose.time * 2 * Math.PI) / 4);

  ctx.save();
  ctx.translate(0, pose.hop);

  drawTail(ctx, pose, p);
  drawBody(ctx, breath, p, outfit);

  // The head: tilted about the neck, leaning in when listening, rising a touch on each breath.
  ctx.save();
  ctx.translate(NECK.x, NECK.y + pose.dip - breath * 0.6);
  ctx.rotate(pose.tilt);
  ctx.translate(-NECK.x, -NECK.y);
  if (outfit === "casual") drawHood(ctx);
  drawHead(ctx, pose, p, outfit, small);
  drawHeadwear(ctx, pose, outfit, small);
  ctx.restore();

  drawNeckwear(ctx, pose, outfit);
  ctx.restore();

  if (!small) {
    if (pose.think > 0.01) drawDots(ctx, pose, options.ink);
    if (pose.listen > 0.01) drawWaves(ctx, pose, options.ink);
  }
  if (pose.sparkle > 0.01) drawSparkles(ctx, pose);
  if (options.speakerMark) drawSpeaker(ctx, options.ink);
}

function fillPath(ctx: Ctx, color: string, path: Path2D | (() => void), edge?: string | null) {
  ctx.fillStyle = color;
  if (path instanceof Path2D) {
    ctx.fill(path);
  } else {
    ctx.beginPath();
    path();
    ctx.fill();
  }
  if (edge) {
    ctx.strokeStyle = edge;
    ctx.lineWidth = 1.2;
    if (path instanceof Path2D) ctx.stroke(path);
    else ctx.stroke();
  }
}

function drawTail(ctx: Ctx, pose: Pose, p: Palette) {
  ctx.save();
  ctx.translate(72, 94);
  // A slow swish; quicker and wider when glad.
  const speed = pose.smile > 0.5 ? 3 : 1;
  ctx.rotate(0.22 * Math.sin((pose.time * 2 * Math.PI * speed) / 3.2));
  ctx.beginPath();
  ctx.moveTo(0, 0);
  ctx.bezierCurveTo(14, 0, 20, -10, 17, -24);
  ctx.bezierCurveTo(15.5, -31, 9, -32, 7, -27);
  if (p.edge) {
    ctx.strokeStyle = p.edge;
    ctx.lineWidth = 9.4;
    ctx.stroke();
  }
  ctx.strokeStyle = p.fur;
  ctx.lineWidth = 7;
  ctx.stroke();
  ctx.restore();
}

function bodyPath(breath: number) {
  // Breathing widens and lifts the chest a little, from the bottom up.
  const lift = 1.2 * breath;
  const path = new Path2D();
  path.moveTo(22, 100);
  path.bezierCurveTo(22, 84, 28, 70 - lift, 50, 70 - lift);
  path.bezierCurveTo(72, 70 - lift, 78, 84, 78, 100);
  path.closePath();
  return path;
}

function drawBody(ctx: Ctx, breath: number, p: Palette, outfit: Outfit) {
  const body = bodyPath(breath);
  if (outfit === "casual") {
    fillPath(ctx, HOODIE, body);
    // The pocket.
    fillPath(ctx, HOODIE_SHADE, () => ctx.roundRect(36, 89, 28, 11, 4));
    return;
  }
  fillPath(ctx, p.fur, body, p.edge);
  fillPath(ctx, p.light, () => ctx.ellipse(50, 91, 13, 11, 0, 0, Math.PI * 2));
}

function drawHead(ctx: Ctx, pose: Pose, p: Palette, outfit: Outfit, small: boolean) {
  // Ears, perked a little when listening.
  const perk = pose.listen * 2;
  for (const side of [-1, 1]) {
    const ear = new Path2D();
    ear.moveTo(50 + side * 26, 38);
    ear.lineTo(50 + side * (27 + perk * 0.5), 14 - perk);
    ear.lineTo(50 + side * 8, 26);
    ear.closePath();
    ctx.lineWidth = 5;
    ctx.strokeStyle = p.edge ?? p.fur;
    ctx.stroke(ear);
    fillPath(ctx, p.fur, ear);
    const inner = new Path2D();
    inner.moveTo(50 + side * 22.5, 32);
    inner.lineTo(50 + side * (25 + perk * 0.5), 19 - perk);
    inner.lineTo(50 + side * 14, 27);
    inner.closePath();
    fillPath(ctx, p.innerEar, inner);
  }

  fillPath(ctx, p.fur, () => ctx.ellipse(HEAD.x, HEAD.y, HEAD.rx, HEAD.ry, 0, 0, Math.PI * 2), p.edge);
  // The muzzle, lighter.
  fillPath(ctx, p.light, () => ctx.ellipse(50, 59, 11, 8, 0, 0, Math.PI * 2));

  if (outfit === "artsy" || pose.smile > 0.01) {
    ctx.globalAlpha = outfit === "artsy" ? 0.45 : 0.45 * pose.smile;
    fillPath(ctx, "#ff7f8e", () => {
      ctx.ellipse(32, 57, 5, 3, 0, 0, Math.PI * 2);
      ctx.moveTo(73, 57);
      ctx.ellipse(68, 57, 5, 3, 0, 0, Math.PI * 2);
    });
    ctx.globalAlpha = 1;
  }

  drawEyes(ctx, pose, p);
  drawMouth(ctx, pose, p);

  if (!small) {
    // Whiskers.
    ctx.strokeStyle = p.eye;
    ctx.globalAlpha = 0.35;
    ctx.lineWidth = 0.9;
    ctx.beginPath();
    for (const side of [-1, 1]) {
      ctx.moveTo(50 + side * 13, 57);
      ctx.lineTo(50 + side * 27, 54);
      ctx.moveTo(50 + side * 13, 60);
      ctx.lineTo(50 + side * 27, 61);
    }
    ctx.stroke();
    ctx.globalAlpha = 1;
  }
}

function drawEyes(ctx: Ctx, pose: Pose, p: Palette) {
  const open = pose.eyes * (1 - pose.smile);
  for (const side of [-1, 1]) {
    const x = 50 + side * EYE_X + pose.lookX * 1.6;
    const y = EYE_Y + pose.lookY * 1.6;
    if (pose.smile > 0.5) {
      // ^^: happy, squeezed shut.
      ctx.strokeStyle = p.eye;
      ctx.lineWidth = 2.6;
      ctx.beginPath();
      ctx.moveTo(x - 4.5, y + 1.5);
      ctx.quadraticCurveTo(x, y - 5, x + 4.5, y + 1.5);
      ctx.stroke();
      continue;
    }
    const ry = Math.max(5.4 * open, 0.6);
    fillPath(ctx, p.eye, () => ctx.ellipse(x, y, 4.3, ry, 0, 0, Math.PI * 2));
    if (ry > 2.5) {
      fillPath(ctx, p.glint, () => ctx.arc(x + 1.4 + pose.lookX * 0.4, y - 2 + pose.lookY * 0.4, 1.5, 0, Math.PI * 2));
    }
  }
}

function drawMouth(ctx: Ctx, pose: Pose, p: Palette) {
  // The nose.
  fillPath(ctx, "#e86b7a", () => {
    ctx.moveTo(47, 54.5);
    ctx.lineTo(53, 54.5);
    ctx.quadraticCurveTo(50, 59, 50, 58);
    ctx.quadraticCurveTo(50, 59, 47, 54.5);
  });
  ctx.strokeStyle = p.eye;
  ctx.lineWidth = 1.5;
  const open = pose.mouth;
  if (open > 0.04) {
    const h = 1 + 7 * open;
    const w = 3.4 + 2 * open;
    fillPath(ctx, "#5a2a2e", () => ctx.ellipse(50, 60 + h / 2, w, h / 2, 0, 0, Math.PI * 2));
    if (open > 0.35) {
      fillPath(ctx, "#ef8a96", () => ctx.ellipse(50, 60 + h - 1.6, w * 0.6, 1.6, 0, 0, Math.PI * 2));
    }
    return;
  }
  // Closed: the cat's ω, curving up when glad.
  const curl = 2.4 + pose.smile * 1.2;
  ctx.beginPath();
  ctx.moveTo(50, 58);
  ctx.quadraticCurveTo(48, 58 + curl, 44.5, 58.5);
  ctx.moveTo(50, 58);
  ctx.quadraticCurveTo(52, 58 + curl, 55.5, 58.5);
  ctx.stroke();
}

// Outfit colors: fixed, whatever the fur.
const HOODIE = "#5b7fbf";
const HOODIE_SHADE = "#4a6aa6";
const DARK = "#3a2f2a";

function drawHood(ctx: Ctx) {
  fillPath(ctx, HOODIE_SHADE, () => ctx.ellipse(50, 62, 36, 20, 0, 0, Math.PI * 2));
}

function drawHeadwear(ctx: Ctx, pose: Pose, outfit: Outfit, small: boolean) {
  switch (outfit) {
    case "classic": {
      // Round glasses, catching the light while thinking.
      ctx.strokeStyle = DARK;
      ctx.lineWidth = 1.8;
      ctx.beginPath();
      ctx.arc(50 - EYE_X, EYE_Y, 7.6, 0, Math.PI * 2);
      ctx.moveTo(50 + EYE_X + 7.6, EYE_Y);
      ctx.arc(50 + EYE_X, EYE_Y, 7.6, 0, Math.PI * 2);
      ctx.moveTo(50 - EYE_X + 7.6, EYE_Y - 1);
      ctx.quadraticCurveTo(50, EYE_Y - 4, 50 + EYE_X - 7.6, EYE_Y - 1);
      ctx.stroke();
      if (pose.think > 0.05) {
        ctx.strokeStyle = "#ffffff";
        ctx.globalAlpha = pose.think * (0.5 + 0.4 * Math.sin(pose.time * 4));
        ctx.lineWidth = 1.6;
        ctx.beginPath();
        for (const x of [50 - EYE_X, 50 + EYE_X]) {
          ctx.moveTo(x + 1, EYE_Y - 5.5);
          ctx.lineTo(x + 5, EYE_Y - 1.5);
        }
        ctx.stroke();
        ctx.globalAlpha = 1;
      }
      if (!small) {
        // A pencil behind the right ear.
        ctx.save();
        ctx.translate(74, 27);
        ctx.rotate(-0.55);
        fillPath(ctx, "#f4c542", () => ctx.rect(-10, -2, 18, 4));
        fillPath(ctx, "#f29fb0", () => ctx.rect(-12.5, -2, 2.5, 4));
        fillPath(ctx, "#e8cfa0", () => {
          ctx.moveTo(8, -2);
          ctx.lineTo(12, 0);
          ctx.lineTo(8, 2);
        });
        ctx.restore();
      }
      return;
    }
    case "casual": {
      // Headphones: a band over the head, cups at the sides.
      ctx.strokeStyle = DARK;
      ctx.lineWidth = 3.6;
      ctx.beginPath();
      ctx.ellipse(HEAD.x, HEAD.y + 2, HEAD.rx + 1, HEAD.ry + 3, 0, Math.PI * 1.06, Math.PI * 1.94);
      ctx.stroke();
      for (const side of [-1, 1]) {
        fillPath(ctx, DARK, () => ctx.roundRect(50 + side * 30 - 4, 41, 8, 15, 3.5));
        fillPath(ctx, HOODIE, () => ctx.roundRect(50 + side * 30 - 2, 44, 4, 9, 2));
      }
      return;
    }
    case "sporty": {
      // A headband across the brow, between the ears.
      const band = (color: string, width: number) => {
        ctx.strokeStyle = color;
        ctx.lineWidth = width;
        ctx.beginPath();
        ctx.ellipse(HEAD.x, HEAD.y + 6, HEAD.rx - 1.5, HEAD.ry - 2, 0, Math.PI * 1.13, Math.PI * 1.87);
        ctx.stroke();
      };
      band("#f5f5f5", 6.5);
      band("#e74c3c", 2);
      return;
    }
    case "artsy": {
      // A beret, worn to one side, hopping a little more than the cat.
      ctx.save();
      ctx.translate(43, 26 + pose.hop * 0.4);
      ctx.rotate(-0.22);
      fillPath(ctx, "#8e3b46", () => ctx.ellipse(0, 0, 23, 9, 0, 0, Math.PI * 2));
      fillPath(ctx, "#7a2f3a", () => ctx.ellipse(0, 4, 21, 3.5, 0, 0, Math.PI * 2));
      fillPath(ctx, "#8e3b46", () => ctx.ellipse(1, -9.5, 2, 2.6, 0, 0, Math.PI * 2));
      ctx.restore();
      return;
    }
    case "cat":
      return;
  }
}

function drawNeckwear(ctx: Ctx, pose: Pose, outfit: Outfit) {
  // Neckwear swings a little with the voice.
  const swing = pose.mouth * 0.12 * Math.sin(pose.time * 9);
  switch (outfit) {
    case "classic": {
      ctx.save();
      ctx.translate(NECK.x, NECK.y);
      ctx.rotate(swing);
      fillPath(ctx, "#c0392b", () => {
        ctx.moveTo(0, 0);
        ctx.lineTo(-10, -5);
        ctx.lineTo(-10, 5);
        ctx.closePath();
        ctx.moveTo(0, 0);
        ctx.lineTo(10, -5);
        ctx.lineTo(10, 5);
        ctx.closePath();
      });
      fillPath(ctx, "#a93226", () => ctx.roundRect(-3, -3, 6, 6, 1.5));
      ctx.restore();
      return;
    }
    case "casual": {
      // The hoodie's strings.
      ctx.strokeStyle = "#f2f2f2";
      ctx.lineWidth = 1.5;
      ctx.beginPath();
      for (const x of [44, 56]) {
        ctx.moveTo(x, 75);
        ctx.lineTo(x - 0.5 + swing * 8, 86);
      }
      ctx.stroke();
      return;
    }
    case "sporty": {
      // A whistle on a lanyard.
      ctx.strokeStyle = "#2f80ed";
      ctx.lineWidth = 1.6;
      ctx.beginPath();
      ctx.moveTo(37, 74);
      ctx.lineTo(50, 86);
      ctx.lineTo(63, 74);
      ctx.stroke();
      ctx.save();
      ctx.translate(50, 87);
      ctx.rotate(swing * 2);
      fillPath(ctx, "#c9ced6", () => {
        ctx.roundRect(-2, 0, 9, 4.4, 1.5);
        ctx.moveTo(1.5, 5.5);
        ctx.arc(-1, 5.5, 3.6, 0, Math.PI * 2);
      });
      fillPath(ctx, "#8e959f", () => ctx.arc(-1, 5.5, 1.3, 0, Math.PI * 2));
      ctx.restore();
      return;
    }
    case "artsy": {
      // A scarf, its end hanging down one side.
      fillPath(ctx, "#e2a03f", () => ctx.roundRect(28, 69, 44, 9, 4.5));
      ctx.save();
      ctx.translate(61, 74);
      ctx.rotate(-0.08 + swing);
      fillPath(ctx, "#d18f2e", () => ctx.roundRect(-4, 0, 9, 20, 2.5));
      ctx.strokeStyle = "#d18f2e";
      ctx.lineWidth = 1.2;
      ctx.beginPath();
      for (const x of [-3, 0.5, 4]) {
        ctx.moveTo(x, 20);
        ctx.lineTo(x, 23);
      }
      ctx.stroke();
      ctx.restore();
      return;
    }
    case "cat":
      return;
  }
}

function drawDots(ctx: Ctx, pose: Pose, ink: string) {
  ctx.fillStyle = ink;
  for (let i = 0; i < 3; i++) {
    const jump = Math.max(0, Math.sin(pose.time * 2 * Math.PI * 1.2 - i * 0.9));
    ctx.globalAlpha = pose.think * (0.45 + 0.4 * jump);
    ctx.beginPath();
    ctx.arc(80 + i * 6.5, 12 - jump * 2.5, 2.2, 0, Math.PI * 2);
    ctx.fill();
  }
  ctx.globalAlpha = 1;
}

function drawWaves(ctx: Ctx, pose: Pose, ink: string) {
  ctx.strokeStyle = ink;
  ctx.lineWidth = 1.8;
  for (let i = 0; i < 3; i++) {
    // Each arc swells in turn, as if sound comes in.
    const phase = (pose.time * 1.5 - i / 3) % 1;
    ctx.globalAlpha = pose.listen * 0.7 * Math.sin(Math.PI * ((phase + 1) % 1));
    ctx.beginPath();
    ctx.arc(85, 38, 4 + i * 4, -Math.PI / 3.2, Math.PI / 3.2);
    ctx.stroke();
  }
  ctx.globalAlpha = 1;
}

const SPARKLES = [
  { x: 14, y: 20, delay: 0 },
  { x: 86, y: 16, delay: 0.15 },
  { x: 88, y: 60, delay: 0.3 },
  { x: 12, y: 62, delay: 0.22 },
];

function drawSparkles(ctx: Ctx, pose: Pose) {
  const spark = new Path2D(SPARK);
  ctx.fillStyle = "#ffc53d";
  for (const s of SPARKLES) {
    // Each pops up, then shrinks away as the joy runs out.
    const t = Math.min(Math.max((pose.joy - s.delay) / 0.35, 0), 1);
    const scale = pose.sparkle * Math.sin(Math.PI * t);
    if (scale <= 0.01) continue;
    ctx.save();
    ctx.translate(s.x, s.y);
    ctx.rotate(t * 0.8);
    ctx.scale(scale, scale);
    ctx.fill(spark);
    ctx.restore();
  }
}

function drawSpeaker(ctx: Ctx, ink: string) {
  ctx.save();
  ctx.translate(86, 86);
  ctx.fillStyle = ink;
  ctx.strokeStyle = ink;
  ctx.beginPath();
  ctx.moveTo(-6, -2.5);
  ctx.lineTo(-3, -2.5);
  ctx.lineTo(1, -6);
  ctx.lineTo(1, 6);
  ctx.lineTo(-3, 2.5);
  ctx.lineTo(-6, 2.5);
  ctx.closePath();
  ctx.fill();
  ctx.lineWidth = 1.6;
  ctx.beginPath();
  ctx.arc(1, 0, 5, -Math.PI / 4, Math.PI / 4);
  ctx.moveTo(1 + 8.5 * Math.cos(-Math.PI / 4), 8.5 * Math.sin(-Math.PI / 4));
  ctx.arc(1, 0, 8.5, -Math.PI / 4, Math.PI / 4);
  ctx.stroke();
  ctx.restore();
}
