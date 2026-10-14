/**
 * Draws the tutor cat (ADR 0032 §4): one cat sitting front on in a 100×100 box, outlined in
 * dark brown, with an outfit layered on top. The fur is the learner's color; the belly, inner
 * ear and eye colors come from it, outfits keep their own. The thinking dots, sound waves and
 * speaker mark use `ink`, the element's text color, so they suit the theme.
 */

import type { Pose } from "./avatar-state";

/** The outfits; ids are the backend's `TUTOR_AVATARS`. `cat` wears nothing. */
export const OUTFITS = ["cat", "classic", "casual", "sporty", "artsy"] as const;
export type Outfit = (typeof OUTFITS)[number];

/** Orange: the fur when the learner hasn't picked one. */
export const DEFAULT_FUR = "#e98b60";

/** Furs offered to pick from (any `#rrggbb` is drawn). */
export const FUR_SWATCHES = [
  "#e98b60", // orange
  "#eab75f", // gold
  "#c4ab92", // beige
  "#929ba5", // grey
  "#829cb8", // blue
  "#48484f", // black
  "#f1eadf", // white
  "#e7a5b6", // pink
] as const;

/** The outline around everything, whatever the fur. */
export const OUTLINE = "#563f39";

export type Palette = {
  fur: string;
  shade: string;
  /** Belly, muzzle and paws. */
  light: string;
  innerEar: string;
  /** Eyes. */
  eye: string;
  /** The glint in the eyes. */
  glint: string;
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
const CREAM: Rgb = [255, 244, 230];
const PINK: Rgb = [255, 214, 200];

/** The colors for a cat of `fur` (`#rrggbb`; anything else gives the default). */
export function paletteFor(fur: string | null | undefined): Palette {
  const base = parseHex(fur ?? "") ?? parseHex(DEFAULT_FUR)!;
  const dark = luminance(base) < 0.1;
  return {
    fur: toHex(base),
    shade: toHex(dark ? mix(base, WHITE, 0.12) : mix(base, BLACK, 0.18)),
    // A dark cat keeps a grey belly; a light one gets cream.
    light: toHex(dark ? mix(base, WHITE, 0.38) : mix(base, CREAM, 0.85)),
    innerEar: toHex(mix(base, PINK, 0.6)),
    // A dark cat gets yellow eyes, so they still show.
    eye: dark ? "#f1cb78" : "#4a3631",
    glint: "#ffffff",
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
  /** The AI hair clip: opening the pet now has the tutor speak first (ADR 0041 §4). */
  clip?: boolean;
};

type Ctx = CanvasRenderingContext2D;

// Where things are in the 100×100 box.
const NECK = { x: 50, y: 64 };
const EYE_X = 12;
const EYE_Y = 41;
const LINE = 2.6;
const BLUSH = "#e2756b";
const GOLD = "#e7b95c";
/** The AI marks' indigo (`--ai`, light theme): the same on light and dark pages. */
const AI_INDIGO = "#5753c9";

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
  drawHead(ctx, pose, p, outfit, small);
  drawHeadwear(ctx, pose, outfit, small);
  if (options.clip) drawClip(ctx);
  ctx.restore();

  drawNeckwear(ctx, pose, outfit);
  ctx.restore();

  if (!small) {
    if (pose.think > 0.01) drawDots(ctx, pose, options.ink);
    if (pose.listen > 0.01) drawWaves(ctx, pose, options.ink);
    if (pose.sleep > 0.01) drawZs(ctx, pose, options.ink);
  }
  if (pose.sparkle > 0.01) drawSparkles(ctx, pose);
  if (options.speakerMark) drawSpeaker(ctx, options.ink);
}

/** Fills `path` with `color`, then outlines it (`line` wide; 0 for no outline). */
function paint(ctx: Ctx, color: string, path: Path2D | (() => void), line = LINE) {
  ctx.fillStyle = color;
  if (path instanceof Path2D) {
    ctx.fill(path);
  } else {
    ctx.beginPath();
    path();
    ctx.fill();
  }
  if (line > 0) {
    ctx.strokeStyle = OUTLINE;
    ctx.lineWidth = line;
    if (path instanceof Path2D) ctx.stroke(path);
    else ctx.stroke();
  }
}

function stroke(ctx: Ctx, color: string, width: number, path: () => void) {
  ctx.strokeStyle = color;
  ctx.lineWidth = width;
  ctx.beginPath();
  path();
  ctx.stroke();
}

function drawTail(ctx: Ctx, pose: Pose, p: Palette) {
  ctx.save();
  ctx.translate(72, 92);
  // A slow swish; quicker and wider when glad.
  const speed = pose.smile > 0.5 ? 3 : 1;
  ctx.rotate(0.18 * Math.sin((pose.time * 2 * Math.PI * speed) / 3.2));
  const curl = () => {
    ctx.moveTo(-4, 2);
    ctx.bezierCurveTo(12, 2, 19, -8, 16, -20);
    ctx.bezierCurveTo(14.5, -27, 7.5, -28, 8, -22);
  };
  stroke(ctx, OUTLINE, 6 + 2 * LINE, curl);
  stroke(ctx, p.fur, 6, curl);
  ctx.restore();
}

function bodyPath(breath: number) {
  // Breathing widens and lifts the chest a little, from the bottom up.
  const lift = 1.2 * breath;
  const path = new Path2D();
  path.moveTo(23, 104);
  path.bezierCurveTo(23, 84, 30, 61 - lift, 50, 60 - lift);
  path.bezierCurveTo(70, 61 - lift, 77, 84, 77, 104);
  path.closePath();
  return path;
}

// Outfit colors: fixed, whatever the fur.
const VEST = "#be9673";
const VEST_SHADE = "#9b765b";
const HOODIE = "#7d99b8";
const HOODIE_SHADE = "#587493";
const TANK = "#8eaa94";
const SMOCK = "#f0ddc3";
const RED = "#a85d58";
const RED_SHADE = "#844747";
const WHITE_TRIM = "#fbf3e4";

function drawBody(ctx: Ctx, breath: number, p: Palette, outfit: Outfit) {
  const body = bodyPath(breath);
  paint(ctx, p.fur, body, 0);
  ctx.save();
  ctx.clip(body);
  switch (outfit) {
    case "cat":
      paint(ctx, p.light, () => ctx.ellipse(50, 85, 15, 17, 0, 0, Math.PI * 2), 0);
      break;
    case "classic":
      // A sweater vest, V-necked, buttoned down the middle.
      paint(ctx, VEST, () => ctx.rect(0, 0, 100, 104), 0);
      paint(ctx, VEST_SHADE, () => {
        ctx.moveTo(38, 58);
        ctx.lineTo(50, 78);
        ctx.lineTo(62, 58);
      }, 0);
      stroke(ctx, VEST_SHADE, 1.3, () => {
        ctx.moveTo(50, 78);
        ctx.lineTo(50, 104);
      });
      break;
    case "casual":
      // A hoodie with a front pocket.
      paint(ctx, HOODIE, () => ctx.rect(0, 0, 100, 104), 0);
      paint(ctx, HOODIE_SHADE, () => ctx.roundRect(38, 77, 24, 12, 4), 1.8);
      break;
    case "sporty":
      // A tank top with a white V neck.
      paint(ctx, TANK, () => ctx.rect(0, 0, 100, 104), 0);
      paint(ctx, p.fur, () => {
        ctx.moveTo(36, 56);
        ctx.lineTo(50, 76);
        ctx.lineTo(64, 56);
      }, 0);
      stroke(ctx, WHITE_TRIM, 2.4, () => {
        ctx.moveTo(36, 56);
        ctx.lineTo(50, 76);
        ctx.lineTo(64, 56);
      });
      break;
    case "artsy":
      // A painter's smock.
      paint(ctx, SMOCK, () => ctx.rect(0, 0, 100, 104), 0);
      break;
  }
  ctx.restore();
  ctx.strokeStyle = OUTLINE;
  ctx.lineWidth = LINE;
  ctx.stroke(body);
  // Front paws.
  for (const x of [35, 54]) paint(ctx, p.light, () => ctx.roundRect(x, 90, 11, 14, 5.5));
}

function headPath() {
  // Wider than tall, with full cheeks.
  const path = new Path2D();
  path.moveTo(50, 19);
  path.bezierCurveTo(72, 19, 82, 28, 82, 43);
  path.bezierCurveTo(82, 58, 70, 65, 50, 65);
  path.bezierCurveTo(30, 65, 18, 58, 18, 43);
  path.bezierCurveTo(18, 28, 28, 19, 50, 19);
  return path;
}

function drawHead(ctx: Ctx, pose: Pose, p: Palette, outfit: Outfit, small: boolean) {
  // Ears, perked a little when listening.
  const perk = pose.listen * 2;
  for (const side of [-1, 1]) {
    paint(ctx, p.fur, () => {
      ctx.moveTo(50 + side * 31, 38);
      ctx.lineTo(50 + side * (28 + perk * 0.5), 9 - perk);
      ctx.lineTo(50 + side * 9, 23);
      ctx.closePath();
    });
    paint(ctx, p.innerEar, () => {
      ctx.moveTo(50 + side * 25.5, 28);
      ctx.lineTo(50 + side * (26 + perk * 0.5), 15 - perk);
      ctx.lineTo(50 + side * 15, 23.5);
      ctx.closePath();
    }, 0);
  }

  const head = headPath();
  paint(ctx, p.fur, head, 0);
  ctx.save();
  ctx.clip(head);
  // The muzzle, lighter.
  paint(ctx, p.light, () => ctx.ellipse(50, 57, 19, 10, 0, 0, Math.PI * 2), 0);
  if (outfit === "sporty") {
    // A headband across the brow, with a gold stripe.
    const band = () => {
      ctx.moveTo(14, 32);
      ctx.quadraticCurveTo(50, 17, 86, 32);
    };
    stroke(ctx, OUTLINE, 7 + 2 * LINE, band);
    stroke(ctx, WHITE_TRIM, 7, band);
    stroke(ctx, GOLD, 1.8, band);
  }
  ctx.restore();
  ctx.strokeStyle = OUTLINE;
  ctx.lineWidth = LINE;
  ctx.stroke(head);

  // Blush.
  ctx.globalAlpha = 0.9;
  for (const side of [-1, 1]) paint(ctx, BLUSH, () => ctx.ellipse(50 + side * 20, 50, 4.6, 2.6, 0, 0, Math.PI * 2), 0);
  ctx.globalAlpha = 1;

  drawEyes(ctx, pose, p);
  drawMouth(ctx, pose);

  if (!small) {
    // Whiskers, out past the cheeks.
    stroke(ctx, OUTLINE, 1.3, () => {
      for (const side of [-1, 1]) {
        ctx.moveTo(50 + side * 25, 48.5);
        ctx.lineTo(50 + side * 37, 46.5);
        ctx.moveTo(50 + side * 25, 52.5);
        ctx.lineTo(50 + side * 37, 53.5);
      }
    });
  }
}

function drawEyes(ctx: Ctx, pose: Pose, p: Palette) {
  const open = pose.eyes * (1 - pose.smile);
  for (const side of [-1, 1]) {
    const x = 50 + side * EYE_X + pose.lookX * 1.6;
    const y = EYE_Y + pose.lookY * 1.6;
    if (pose.sleep > 0.5) {
      // Asleep: shut, curving down.
      stroke(ctx, OUTLINE, 2.4, () => {
        ctx.moveTo(x - 4, y - 0.5);
        ctx.quadraticCurveTo(x, y + 3.5, x + 4, y - 0.5);
      });
      continue;
    }
    if (pose.smile > 0.5) {
      // ^^: happy, squeezed shut.
      stroke(ctx, OUTLINE, 2.4, () => {
        ctx.moveTo(x - 4, y + 1.5);
        ctx.quadraticCurveTo(x, y - 4.5, x + 4, y + 1.5);
      });
      continue;
    }
    const ry = Math.max(5.4 * open, 0.6);
    paint(ctx, p.eye, () => ctx.ellipse(x, y, 4, ry, 0, 0, Math.PI * 2), 0);
    if (ry > 2.5) {
      paint(ctx, p.glint, () => ctx.arc(x + 1.1 + pose.lookX * 0.4, y - 2.2 + pose.lookY * 0.4, 1.4, 0, Math.PI * 2), 0);
    }
  }
}

function drawMouth(ctx: Ctx, pose: Pose) {
  // The nose.
  paint(ctx, OUTLINE, () => {
    ctx.moveTo(47.8, 49.4);
    ctx.lineTo(52.2, 49.4);
    ctx.lineTo(50, 51.8);
    ctx.closePath();
  }, 1);
  // Open when talking, and in a grin when glad.
  const open = Math.max(pose.mouth, pose.smile > 0.5 ? 0.6 : 0);
  if (open > 0.04) {
    const w = 3 + 1.6 * open;
    const d = 1.2 + 5 * open;
    paint(ctx, OUTLINE, () => {
      ctx.moveTo(50 - w, 53);
      ctx.lineTo(50 + w, 53);
      ctx.ellipse(50, 53, w, d, 0, 0, Math.PI);
    }, 1);
    if (d > 3) paint(ctx, BLUSH, () => ctx.ellipse(50, 53 + d - 1.4, w * 0.55, 1.3, 0, 0, Math.PI * 2), 0);
    return;
  }
  if (pose.think > 0.5) {
    // A small frown, puzzling.
    stroke(ctx, OUTLINE, 1.5, () => {
      ctx.moveTo(47, 55.5);
      ctx.quadraticCurveTo(50, 53.2, 53, 55.5);
    });
    return;
  }
  // Closed: the cat's ω.
  stroke(ctx, OUTLINE, 1.5, () => {
    ctx.moveTo(50, 51.8);
    ctx.quadraticCurveTo(48.6, 55.4, 45.5, 54);
    ctx.moveTo(50, 51.8);
    ctx.quadraticCurveTo(51.4, 55.4, 54.5, 54);
  });
}

function drawHeadwear(ctx: Ctx, pose: Pose, outfit: Outfit, small: boolean) {
  switch (outfit) {
    case "classic": {
      // Round glasses, catching the light while thinking.
      stroke(ctx, OUTLINE, 1.8, () => {
        for (const side of [-1, 1]) {
          ctx.moveTo(50 + side * EYE_X + 7, EYE_Y);
          ctx.arc(50 + side * EYE_X, EYE_Y, 7, 0, Math.PI * 2);
          ctx.moveTo(50 + side * (EYE_X + 7), EYE_Y - 1);
          ctx.lineTo(50 + side * 30, EYE_Y - 3);
        }
        ctx.moveTo(50 - EYE_X + 7, EYE_Y - 1);
        ctx.quadraticCurveTo(50, EYE_Y - 4, 50 + EYE_X - 7, EYE_Y - 1);
      });
      if (pose.think > 0.05) {
        ctx.globalAlpha = pose.think * (0.5 + 0.4 * Math.sin(pose.time * 4));
        stroke(ctx, "#ffffff", 1.4, () => {
          for (const x of [50 - EYE_X, 50 + EYE_X]) {
            ctx.moveTo(x + 1.5, EYE_Y - 5);
            ctx.lineTo(x + 4.5, EYE_Y - 2);
          }
        });
        ctx.globalAlpha = 1;
      }
      if (!small) {
        // A pencil behind the right ear.
        ctx.save();
        ctx.translate(81, 14);
        ctx.rotate(-0.95);
        paint(ctx, GOLD, () => ctx.rect(-9, -2, 15, 4), 1.2);
        paint(ctx, SMOCK, () => {
          ctx.moveTo(6, -2);
          ctx.lineTo(10.5, 0);
          ctx.lineTo(6, 2);
          ctx.closePath();
        }, 1.2);
        ctx.restore();
      }
      return;
    }
    case "casual": {
      // Headphones: a band over the head and ears, cups at the sides.
      stroke(ctx, OUTLINE, 3.6, () => ctx.ellipse(50, 40, 35, 35, 0, Math.PI * 1.08, Math.PI * 1.92));
      for (const side of [-1, 1]) paint(ctx, HOODIE, () => ctx.roundRect(50 + side * 33 - 4, 35, 8, 16, 4));
      return;
    }
    case "artsy": {
      // A beret, worn to one side, hopping a little more than the cat.
      ctx.save();
      ctx.translate(40, 19 + pose.hop * 0.4);
      ctx.rotate(-0.22);
      stroke(ctx, OUTLINE, 1.8, () => {
        ctx.moveTo(2, -8);
        ctx.quadraticCurveTo(2, -12, 4.5, -13);
      });
      paint(ctx, RED, () => ctx.ellipse(0, 0, 24, 8.5, 0, 0, Math.PI * 2));
      paint(ctx, RED_SHADE, () => ctx.ellipse(0, 4.5, 20, 2.6, 0, 0, Math.PI * 2), 0);
      ctx.restore();
      return;
    }
    case "sporty": // the headband is drawn with the head
    case "cat":
      return;
  }
}

/**
 * A hair clip in front of the right ear's root, tilted with the head: an indigo bar with a
 * white ✦. Clear of every outfit's headwear (the beret sits left, the pencil behind the
 * ear, the headphone band over the top); on the sporty headband it clips the band.
 */
function drawClip(ctx: Ctx) {
  ctx.save();
  ctx.translate(66, 24);
  ctx.rotate(0.55);
  paint(ctx, AI_INDIGO, () => ctx.roundRect(-8, -4, 16, 8, 4), 1.6);
  ctx.fillStyle = "#ffffff";
  ctx.scale(0.42, 0.42);
  ctx.fill(new Path2D(SPARK));
  ctx.restore();
}

function drawNeckwear(ctx: Ctx, pose: Pose, outfit: Outfit) {
  // Neckwear swings a little with the voice.
  const swing = pose.mouth * 0.12 * Math.sin(pose.time * 9);
  switch (outfit) {
    case "classic": {
      ctx.save();
      ctx.translate(NECK.x, NECK.y + 3);
      ctx.rotate(swing);
      paint(ctx, RED, () => {
        ctx.moveTo(-2, 0);
        ctx.lineTo(-9, -4.5);
        ctx.lineTo(-9, 4.5);
        ctx.closePath();
        ctx.moveTo(2, 0);
        ctx.lineTo(9, -4.5);
        ctx.lineTo(9, 4.5);
        ctx.closePath();
      }, 1.8);
      paint(ctx, RED_SHADE, () => ctx.roundRect(-2.6, -2.6, 5.2, 5.2, 1.5), 1.6);
      ctx.restore();
      return;
    }
    case "casual": {
      // The hoodie's collar and strings.
      stroke(ctx, HOODIE_SHADE, 4, () => ctx.ellipse(50, 61, 19, 7, 0, Math.PI * 0.08, Math.PI * 0.92));
      stroke(ctx, WHITE_TRIM, 1.6, () => {
        for (const x of [45, 55]) {
          ctx.moveTo(x, 69);
          ctx.lineTo(x + swing * 8, 78);
        }
      });
      return;
    }
    case "sporty": {
      // A gold medal on the chest.
      ctx.save();
      ctx.translate(50, 76);
      ctx.rotate(swing * 2);
      paint(ctx, GOLD, () => ctx.arc(0, 0, 4.6, 0, Math.PI * 2), 1.8);
      paint(ctx, "#f3d58f", () => ctx.arc(0, 0, 2, 0, Math.PI * 2), 0);
      ctx.restore();
      return;
    }
    case "artsy": {
      // A scarf, its end hanging down one side.
      ctx.save();
      ctx.translate(60, 68);
      ctx.rotate(-0.08 + swing);
      paint(ctx, GOLD, () => ctx.roundRect(-4.5, 0, 9, 18, 2.5), 1.8);
      ctx.restore();
      paint(ctx, GOLD, () => ctx.roundRect(31, 62, 38, 9, 4.5), 1.8);
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
    ctx.arc(83 + i * 5.5, 9 - jump * 2.5, 2, 0, Math.PI * 2);
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
    ctx.arc(86, 40, 3 + i * 3.5, -Math.PI / 3.2, Math.PI / 3.2);
    ctx.stroke();
  }
  ctx.globalAlpha = 1;
}

function drawZs(ctx: Ctx, pose: Pose, ink: string) {
  ctx.fillStyle = ink;
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  for (let i = 0; i < 3; i++) {
    // Each z rises from the head and fades, bigger as it goes; still, they sit in a row.
    const phase = (pose.time / 3 + i / 3) % 1;
    const rise = pose.time > 0 ? phase : i / 3;
    ctx.globalAlpha = pose.sleep * (pose.time > 0 ? Math.sin(Math.PI * rise) : 0.8);
    ctx.font = `bold ${7 + rise * 6}px sans-serif`;
    ctx.fillText("z", 76 + rise * 14, 22 - rise * 16);
  }
  ctx.globalAlpha = 1;
}

const SPARKLES = [
  { x: 11, y: 18, delay: 0 },
  { x: 89, y: 14, delay: 0.15 },
  { x: 91, y: 58, delay: 0.3 },
];

function drawSparkles(ctx: Ctx, pose: Pose) {
  const spark = new Path2D(SPARK);
  ctx.fillStyle = GOLD;
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
