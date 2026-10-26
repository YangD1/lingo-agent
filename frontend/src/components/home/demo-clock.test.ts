import { describe, expect, it } from "vitest";

import { DemoClock, STOP } from "@/components/home/demo-clock";

/** Lets settled promises run their callbacks. */
const flush = () => new Promise((r) => setTimeout(r, 0));

describe("DemoClock", () => {
  it("resolves a wait once enough playing time has passed", async () => {
    const clock = new DemoClock();
    clock.playing = true;
    const run = clock.start();
    let done = false;
    void clock.wait(250, run).then(() => (done = true));
    clock.tick(100);
    clock.tick(100);
    await flush();
    expect(done).toBe(false);
    clock.tick(60);
    await flush();
    expect(done).toBe(true);
  });

  it("stands still while paused (off screen or a hidden tab)", async () => {
    const clock = new DemoClock();
    const run = clock.start();
    let done = false;
    void clock.wait(50, run).then(() => (done = true));
    clock.tick(100);
    await flush();
    expect(done).toBe(false);
    clock.playing = true;
    clock.tick(50);
    await flush();
    expect(done).toBe(true);
  });

  it("counts at most 100 ms per frame, so a long gap doesn't skip the scene ahead", async () => {
    const clock = new DemoClock();
    clock.playing = true;
    const run = clock.start();
    let done = false;
    void clock.wait(150, run).then(() => (done = true));
    clock.tick(5000);
    await flush();
    expect(done).toBe(false);
  });

  it("rejects pending and later waits of a cancelled run with STOP", async () => {
    const clock = new DemoClock();
    clock.playing = true;
    const old = clock.start();
    const pending = clock.wait(100, old);
    const next = clock.start();
    await expect(pending).rejects.toBe(STOP);
    await expect(clock.wait(10, old)).rejects.toBe(STOP);
    // the new run is unaffected
    const fresh = clock.wait(10, next);
    clock.tick(20);
    await expect(fresh).resolves.toBeUndefined();
  });

  it("resolves at once under reduced motion, but still stops a cancelled run", async () => {
    const clock = new DemoClock(true);
    const run = clock.start();
    await expect(clock.wait(10_000, run)).resolves.toBeUndefined();
    clock.cancel();
    await expect(clock.wait(10, run)).rejects.toBe(STOP);
  });
});
