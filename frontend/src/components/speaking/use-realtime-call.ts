"use client";

import { useCallback, useEffect, useReducer, useRef, useState } from "react";

import { MicTapError } from "@/lib/mic-tap";
import {
  callReducer,
  initialCall,
  parseEvent,
  type ServerEvent,
} from "@/lib/realtime-call";
import {
  type CallMicrophone,
  type CallPlayer,
  createCallPlayer,
  openCallMicrophone,
} from "@/lib/realtime-audio";

// After `ended`, how long the tutor's last words may go on playing.
const DRAIN_LIMIT_MS = 15_000;
const DRAIN_POLL_MS = 200;

/** `WS /speech/realtime` through Next's `/api` proxy, on this page's host. */
export function callUrl(scenarioId: string | null): string {
  const scheme = window.location.protocol === "https:" ? "wss" : "ws";
  const query = scenarioId ? `?${new URLSearchParams({ scenario: scenarioId })}` : "";
  return `${scheme}://${window.location.host}/api/speech/realtime${query}`;
}

type Live = {
  socket: WebSocket;
  mic: CallMicrophone | null;
  player: CallPlayer;
  sending: boolean;
  outputRate: number;
};

/**
 * One realtime call (ADR 0030, Q62c): `start` must run in the click handler, since
 * browsers only play audio started by a gesture. It opens the microphone first (so a
 * refusal costs nothing), then the socket; on `ready` the learner's audio goes out at
 * the vendor's rate. When the learner cuts in (`speech_started`) the tutor stops at
 * once and OpenAI is told how much was heard. `hangUp` asks the backend to end; the
 * page leaving closes the socket, which the backend also takes as hanging up.
 */
export function useRealtimeCall() {
  const [state, dispatch] = useReducer(callReducer, initialCall);
  const [level, setLevel] = useState(0);
  const [muted, setMutedState] = useState(false);
  const liveRef = useRef<Live | null>(null);

  const release = useCallback((drain: boolean) => {
    const live = liveRef.current;
    if (!live) return;
    liveRef.current = null;
    live.mic?.close();
    setLevel(0);
    if (live.socket.readyState <= WebSocket.OPEN) live.socket.close();
    if (!drain) {
      live.player.close();
      return;
    }
    // Let the goodbye finish playing.
    const until = Date.now() + DRAIN_LIMIT_MS;
    const timer = window.setInterval(() => {
      if (live.player.busy() && Date.now() < until) return;
      window.clearInterval(timer);
      live.player.close();
    }, DRAIN_POLL_MS);
  }, []);

  const onEvent = useCallback(
    (event: ServerEvent) => {
      const live = liveRef.current;
      if (!live) return;
      switch (event.type) {
        case "ready":
          live.outputRate = event.output_rate;
          live.sending = true;
          live.mic?.send(event.input_rate, (frame) => {
            if (live.sending && live.socket.readyState === WebSocket.OPEN) live.socket.send(frame);
          });
          break;
        case "speech_started":
          if (live.player.busy()) {
            live.socket.send(JSON.stringify({ type: "interrupt", played_ms: live.player.playedMs() }));
          }
          live.player.clear();
          break;
        case "response_done":
          live.player.newReply();
          break;
        case "wrapping_up":
          // The learner talking would cut the goodbye short; the backend ignores it too.
          live.sending = false;
          break;
        case "ended":
          release(true);
          break;
      }
      dispatch({ type: "event", event });
    },
    [release],
  );

  const start = useCallback(
    async (scenarioId: string | null) => {
      if (liveRef.current) return;
      dispatch({ type: "connect" });
      setMutedState(false);
      const player = createCallPlayer();
      let mic: CallMicrophone;
      try {
        mic = await openCallMicrophone(setLevel);
      } catch (e) {
        player.close();
        dispatch({
          type: "lost",
          reason: e instanceof MicTapError ? e.code : "recording_unsupported",
        });
        return;
      }
      const socket = new WebSocket(callUrl(scenarioId));
      socket.binaryType = "arraybuffer";
      const live: Live = { socket, mic, player, sending: false, outputRate: 0 };
      liveRef.current = live;
      socket.onmessage = (message: MessageEvent<ArrayBuffer | string>) => {
        if (liveRef.current !== live) return;
        if (typeof message.data === "string") {
          const event = parseEvent(message.data);
          if (event) onEvent(event);
        } else if (live.outputRate) {
          live.player.play(message.data, live.outputRate);
        }
      };
      // Closed without `ended`: refused at the door (not signed in) or the network.
      socket.onclose = () => {
        if (liveRef.current !== live) return;
        release(false);
        dispatch({ type: "lost", reason: "connection_lost" });
      };
    },
    [onEvent, release],
  );

  const hangUp = useCallback(() => {
    const live = liveRef.current;
    if (!live) return;
    if (live.socket.readyState === WebSocket.OPEN) {
      live.sending = false;
      live.socket.send(JSON.stringify({ type: "end" }));
      return; // `ended` follows
    }
    release(false);
    dispatch({ type: "lost", reason: "hangup" });
  }, [release]);

  const setMuted = useCallback((value: boolean) => {
    liveRef.current?.mic?.setMuted(value);
    setMutedState(value);
  }, []);

  const dismissEnd = useCallback(() => dispatch({ type: "dismiss_end" }), []);

  // The countdown runs locally; `time_warning` puts it right.
  const ticking = state.phase === "live" || state.phase === "wrapping";
  useEffect(() => {
    if (!ticking) return;
    const timer = window.setInterval(() => dispatch({ type: "tick", seconds: 1 }), 1000);
    return () => window.clearInterval(timer);
  }, [ticking]);

  // Leaving the page hangs up: the backend ends the call when the socket closes (Q62g).
  useEffect(() => () => release(false), [release]);

  return { state, level, muted, start, hangUp, setMuted, dismissEnd };
}
