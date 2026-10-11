/**
 * The microphone as raw samples: an AudioWorklet copies each block (mixed down to mono,
 * at the context's own rate) to the page. Shared by the shadowing recorder (16 kHz WAV)
 * and realtime calls (PCM16 frames at the vendor's rate, ADR 0030 §1).
 */

// Loaded from a Blob URL so the worklet needs no separate build step.
const TAP_WORKLET = `
class LingoTap extends AudioWorkletProcessor {
  process(inputs) {
    const channels = inputs[0];
    if (channels && channels.length) {
      const mono = new Float32Array(channels[0].length);
      for (const channel of channels) {
        for (let i = 0; i < mono.length; i++) mono[i] += channel[i] / channels.length;
      }
      this.port.postMessage(mono, [mono.buffer]);
    }
    return true;
  }
}
registerProcessor("lingo-tap", LingoTap);
`;

export function canTapMicrophone(): boolean {
  return (
    typeof AudioContext !== "undefined" &&
    typeof AudioWorkletNode !== "undefined" &&
    !!navigator.mediaDevices?.getUserMedia
  );
}

export type MicTap = {
  /** The samples' rate: the audio context's, usually 48 or 44.1 kHz. */
  rate: number;
  stream: MediaStream;
  /** Receives each block of samples; set it before calling `start`. */
  onSamples: ((samples: Float32Array) => void) | null;
  start: () => void;
  /** Releases the microphone; safe to call twice. */
  close: () => void;
};

export class MicTapError extends Error {
  constructor(readonly code: "microphone_denied" | "recording_unsupported") {
    super(code);
  }
}

/** Asks for the microphone (echo cancelled) and connects the tap; samples flow after `start`. */
export async function openMicTap(): Promise<MicTap> {
  if (!canTapMicrophone()) throw new MicTapError("recording_unsupported");
  let stream: MediaStream;
  try {
    stream = await navigator.mediaDevices.getUserMedia({
      audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true },
    });
  } catch {
    throw new MicTapError("microphone_denied");
  }
  const context = new AudioContext();
  const url = URL.createObjectURL(new Blob([TAP_WORKLET], { type: "text/javascript" }));
  let node: AudioWorkletNode;
  try {
    await context.audioWorklet.addModule(url);
    node = new AudioWorkletNode(context, "lingo-tap");
  } catch {
    stream.getTracks().forEach((track) => track.stop());
    void context.close();
    throw new MicTapError("recording_unsupported");
  } finally {
    URL.revokeObjectURL(url);
  }
  const source = context.createMediaStreamSource(stream);
  // Some browsers only run a worklet that reaches the output: route it there muted.
  const mute = context.createGain();
  mute.gain.value = 0;
  source.connect(node).connect(mute).connect(context.destination);

  let closed = false;
  const tap: MicTap = {
    rate: context.sampleRate,
    stream,
    onSamples: null,
    start: () => {
      node.port.onmessage = (event: MessageEvent<Float32Array>) => tap.onSamples?.(event.data);
      void context.resume();
    },
    close: () => {
      if (closed) return;
      closed = true;
      node.port.onmessage = null;
      source.disconnect();
      node.disconnect();
      stream.getTracks().forEach((track) => track.stop());
      void context.close();
    },
  };
  return tap;
}
