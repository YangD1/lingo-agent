import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { MicTapError } from "@/lib/mic-tap";

import { callUrl, useRealtimeCall } from "./use-realtime-call";

const audio = vi.hoisted(() => ({
  mic: {
    send: vi.fn(),
    setMuted: vi.fn(),
    close: vi.fn(),
  },
  player: {
    play: vi.fn(),
    clear: vi.fn(),
    busy: vi.fn(() => false),
    playedMs: vi.fn(() => 1234),
    newReply: vi.fn(),
    close: vi.fn(),
  },
  openCallMicrophone: vi.fn(),
}));

vi.mock("@/lib/realtime-audio", () => ({
  openCallMicrophone: audio.openCallMicrophone,
  createCallPlayer: () => audio.player,
}));

class FakeSocket {
  static CONNECTING = 0;
  static OPEN = 1;
  static CLOSING = 2;
  static CLOSED = 3;
  static last: FakeSocket | null = null;
  readyState = FakeSocket.OPEN;
  binaryType = "blob";
  sent: (string | ArrayBuffer)[] = [];
  onmessage: ((message: { data: string | ArrayBuffer }) => void) | null = null;
  onclose: (() => void) | null = null;
  constructor(readonly url: string) {
    FakeSocket.last = this;
  }
  send(data: string | ArrayBuffer) {
    this.sent.push(data);
  }
  close() {
    this.readyState = FakeSocket.CLOSED;
  }
  /** The server sends a JSON event or audio. */
  receive(data: object | ArrayBuffer) {
    act(() => this.onmessage?.({ data: data instanceof ArrayBuffer ? data : JSON.stringify(data) }));
  }
  /** The server closes the socket. */
  drop() {
    this.readyState = FakeSocket.CLOSED;
    act(() => this.onclose?.());
  }
  json() {
    return this.sent.filter((d) => typeof d === "string").map((d) => JSON.parse(d as string));
  }
}

const READY = {
  type: "ready",
  session_id: "s1",
  conversation_id: "c1",
  input_rate: 16000,
  output_rate: 24000,
  limit_seconds: 900,
};

let socket: FakeSocket;

async function connect(scenario: string | null = null) {
  const hook = renderHook(() => useRealtimeCall());
  await act(() => hook.result.current.start(scenario));
  socket = FakeSocket.last!;
  return hook;
}

beforeEach(() => {
  vi.stubGlobal("WebSocket", FakeSocket);
  FakeSocket.last = null;
  audio.openCallMicrophone.mockResolvedValue(audio.mic);
  audio.player.busy.mockReturnValue(false);
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.clearAllMocks();
  vi.useRealTimers();
});

describe("callUrl", () => {
  it("goes through the /api proxy on this host, with the scenario", () => {
    expect(callUrl(null)).toBe(`ws://${window.location.host}/api/speech/realtime`);
    expect(callUrl("job_interview")).toMatch(/\/api\/speech\/realtime\?scenario=job_interview$/);
  });
});

describe("useRealtimeCall", () => {
  it("opens the microphone before the socket and sends audio from ready", async () => {
    const { result } = await connect("ordering_food");
    expect(socket.url).toMatch(/scenario=ordering_food/);
    expect(socket.binaryType).toBe("arraybuffer");
    expect(result.current.state.phase).toBe("connecting");
    expect(audio.mic.send).not.toHaveBeenCalled();

    socket.receive(READY);
    expect(result.current.state.phase).toBe("live");
    expect(audio.mic.send).toHaveBeenCalledWith(16000, expect.any(Function));
    const onFrame = audio.mic.send.mock.calls[0][1] as (frame: ArrayBuffer) => void;
    const frame = new ArrayBuffer(3200);
    onFrame(frame);
    expect(socket.sent).toEqual([frame]);
  });

  it("plays the tutor's audio at the output rate", async () => {
    await connect();
    const early = new ArrayBuffer(4);
    socket.receive(early); // before ready: no rate yet
    socket.receive(READY);
    const chunk = new ArrayBuffer(480);
    socket.receive(chunk);
    expect(audio.player.play).toHaveBeenCalledTimes(1);
    expect(audio.player.play).toHaveBeenCalledWith(chunk, 24000);
  });

  it("stops the tutor when the learner cuts in and says how much was heard", async () => {
    await connect();
    socket.receive(READY);
    audio.player.busy.mockReturnValue(true);
    socket.receive({ type: "speech_started" });
    expect(socket.json()).toEqual([{ type: "interrupt", played_ms: 1234 }]);
    expect(audio.player.clear).toHaveBeenCalled();

    audio.player.busy.mockReturnValue(false);
    socket.receive({ type: "speech_started" }); // nothing playing: nothing to cancel
    expect(socket.json()).toHaveLength(1);
  });

  it("starts a new reply after response_done", async () => {
    await connect();
    socket.receive(READY);
    socket.receive({ type: "response_done" });
    expect(audio.player.newReply).toHaveBeenCalled();
  });

  it("stops sending audio while the tutor says goodbye", async () => {
    const { result } = await connect();
    socket.receive(READY);
    socket.receive({ type: "wrapping_up" });
    expect(result.current.state.phase).toBe("wrapping");
    (audio.mic.send.mock.calls[0][1] as (f: ArrayBuffer) => void)(new ArrayBuffer(2));
    expect(socket.sent).toEqual([]);
  });

  it("hangs up by asking the backend, then ends on its answer", async () => {
    vi.useFakeTimers();
    const { result } = await connect();
    socket.receive(READY);
    act(() => result.current.hangUp());
    expect(socket.json()).toEqual([{ type: "end" }]);
    expect(result.current.state.phase).toBe("live");

    socket.receive({ type: "ended", reason: "hangup" });
    expect(result.current.state).toMatchObject({ phase: "ended", end_reason: "hangup" });
    expect(audio.mic.close).toHaveBeenCalled();
    expect(socket.readyState).toBe(FakeSocket.CLOSED);
    // The tutor's last words play out before the player closes.
    expect(audio.player.close).not.toHaveBeenCalled();
    act(() => vi.advanceTimersByTime(300));
    expect(audio.player.close).toHaveBeenCalled();
  });

  it("shows why a call was refused", async () => {
    const { result } = await connect();
    socket.receive({ type: "ended", reason: "refused", code: "realtime_busy" });
    expect(result.current.state).toMatchObject({
      phase: "ended",
      end_reason: "refused",
      refused_code: "realtime_busy",
    });
  });

  it("ends when the socket closes without a word", async () => {
    const { result } = await connect();
    socket.receive(READY);
    socket.drop();
    expect(result.current.state).toMatchObject({ phase: "ended", end_reason: "connection_lost" });
    expect(audio.mic.close).toHaveBeenCalled();
    expect(audio.player.close).toHaveBeenCalled();
  });

  it("does not call when the microphone is refused", async () => {
    audio.openCallMicrophone.mockRejectedValueOnce(new MicTapError("microphone_denied"));
    const { result } = await connect();
    expect(FakeSocket.last).toBeNull();
    expect(result.current.state).toMatchObject({ phase: "ended", end_reason: "microphone_denied" });
    expect(audio.player.close).toHaveBeenCalled();
  });

  it("mutes the microphone", async () => {
    const { result } = await connect();
    act(() => result.current.setMuted(true));
    expect(audio.mic.setMuted).toHaveBeenCalledWith(true);
    expect(result.current.muted).toBe(true);
  });

  it("counts down every second while live", async () => {
    vi.useFakeTimers();
    const { result } = await connect();
    socket.receive(READY);
    act(() => vi.advanceTimersByTime(3000));
    expect(result.current.state.elapsed).toBe(3);
  });

  it("hangs up when the page goes away", async () => {
    const { unmount } = await connect();
    socket.receive(READY);
    unmount();
    expect(socket.readyState).toBe(FakeSocket.CLOSED);
    expect(audio.mic.close).toHaveBeenCalled();
    expect(audio.player.close).toHaveBeenCalled();
  });

  it("can call again after a call ended", async () => {
    const { result } = await connect();
    socket.receive({ type: "ended", reason: "refused", code: "realtime_busy" });
    await act(() => result.current.start(null));
    expect(FakeSocket.last).not.toBe(socket);
    expect(result.current.state.phase).toBe("connecting");
  });
});
