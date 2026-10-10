/**
 * Shadowing recordings go to pronunciation assessment as 16 kHz mono 16-bit WAV: the
 * short-audio API takes no webm and the backend has no ffmpeg (ADR 0028 §5), so the
 * browser encodes them itself.
 */

export const WAV_SAMPLE_RATE = 16000;
const HEADER_BYTES = 44;

/** Joins the recorded chunks into one buffer. */
export function concatSamples(chunks: readonly Float32Array[]): Float32Array {
  const out = new Float32Array(chunks.reduce((n, c) => n + c.length, 0));
  let offset = 0;
  for (const chunk of chunks) {
    out.set(chunk, offset);
    offset += chunk.length;
  }
  return out;
}

/**
 * Resamples to `toRate`. Going down, each output sample averages the input samples it
 * covers (a crude low-pass, enough for speech); going up, it interpolates linearly.
 */
export function resample(input: Float32Array, fromRate: number, toRate: number): Float32Array {
  if (fromRate === toRate) return input.slice();
  const ratio = fromRate / toRate;
  const out = new Float32Array(Math.floor(input.length / ratio));
  for (let i = 0; i < out.length; i++) {
    if (ratio > 1) {
      const start = Math.floor(i * ratio);
      const end = Math.min(input.length, Math.max(start + 1, Math.floor((i + 1) * ratio)));
      let sum = 0;
      for (let j = start; j < end; j++) sum += input[j];
      out[i] = sum / (end - start);
    } else {
      const position = i * ratio;
      const left = Math.floor(position);
      const right = Math.min(left + 1, input.length - 1);
      out[i] = input[left] + (input[right] - input[left]) * (position - left);
    }
  }
  return out;
}

/** A mono 16-bit PCM WAV file of `samples` (-1..1, clipped beyond). */
export function encodeWav(samples: Float32Array, sampleRate: number): ArrayBuffer {
  const buffer = new ArrayBuffer(HEADER_BYTES + samples.length * 2);
  const view = new DataView(buffer);
  const text = (offset: number, value: string) => {
    for (let i = 0; i < value.length; i++) view.setUint8(offset + i, value.charCodeAt(i));
  };
  text(0, "RIFF");
  view.setUint32(4, 36 + samples.length * 2, true);
  text(8, "WAVE");
  text(12, "fmt ");
  view.setUint32(16, 16, true); // fmt chunk size
  view.setUint16(20, 1, true); // PCM
  view.setUint16(22, 1, true); // mono
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, sampleRate * 2, true); // bytes per second
  view.setUint16(32, 2, true); // bytes per frame
  view.setUint16(34, 16, true); // bits per sample
  text(36, "data");
  view.setUint32(40, samples.length * 2, true);
  for (let i = 0; i < samples.length; i++) {
    const s = Math.max(-1, Math.min(1, samples[i]));
    view.setInt16(HEADER_BYTES + i * 2, s < 0 ? s * 0x8000 : s * 0x7fff, true);
  }
  return buffer;
}

/** The recorded chunks as a 16 kHz WAV file, cut to `maxSeconds`. */
export function recordingToWav(
  chunks: readonly Float32Array[],
  inputRate: number,
  maxSeconds: number,
): ArrayBuffer {
  const samples = resample(concatSamples(chunks), inputRate, WAV_SAMPLE_RATE);
  return encodeWav(samples.subarray(0, Math.floor(maxSeconds * WAV_SAMPLE_RATE)), WAV_SAMPLE_RATE);
}
