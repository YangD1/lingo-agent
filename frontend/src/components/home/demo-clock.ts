/** Thrown into a scene's pending waits when it is cancelled. */
export const STOP = Symbol("stop");

/**
 * The home page demo's clock (ADR 0065 §2): waits that only count down while the clock is
 * playing (the window on screen and the tab visible). `cancel()` ends the current run: every
 * pending wait rejects with STOP, and so does any wait the run asks for afterwards, so a scene
 * cut short stops at its next wait. Under reduced motion every wait resolves at once and a
 * scene plays straight to its last frame.
 */
export class DemoClock {
  playing = false;
  private time = 0;
  private run = 0;
  private timers: { at: number; run: number; resolve: () => void; reject: (e: unknown) => void }[] = [];

  constructor(private readonly instant = false) {}

  /** The current run's token; pass it to `wait` so a cancelled run can't keep going. */
  start(): number {
    this.cancel();
    return this.run;
  }

  wait(ms: number, run: number): Promise<void> {
    if (run !== this.run) return Promise.reject(STOP);
    if (this.instant) return Promise.resolve();
    return new Promise((resolve, reject) => this.timers.push({ at: this.time + ms, run, resolve, reject }));
  }

  cancel(): void {
    this.run++;
    for (const t of this.timers.splice(0)) t.reject(STOP);
  }

  /** Advance by `dt` ms of wall time (one animation frame, capped so a background tab can't jump). */
  tick(dt: number): void {
    if (!this.playing) return;
    this.time += Math.min(100, dt);
    const due = this.timers.filter((t) => t.at <= this.time);
    this.timers = this.timers.filter((t) => t.at > this.time);
    for (const t of due) {
      if (t.run === this.run) t.resolve();
      else t.reject(STOP);
    }
  }
}
