"use client";

import {
  CursorRipples,
  FilmGrain,
  FlowingGradient,
  FlutedGlass,
  MeshGradient,
  Shader,
} from "shaders/react";

/**
 * The WebGPU half of the landing backdrops (shaders.com, MIT; ADR 0037). Loaded lazily by
 * landing-backdrop.tsx, so the library stays out of every other page's bundle. Telemetry to
 * shaders.com is off: the page makes no third-party calls.
 */

export type ShaderProps = {
  dark: boolean;
  still: boolean;
  onReady: () => void;
  onUnavailable: () => void;
  className?: string;
};

/* Brand palette (globals.css): coral brand, amber spark, indigo AI accent, ink. */
const CORAL_SOFT = "#FDEBE4";
const CORAL_MID = "#F2A086";
const CORAL = "#F25C3B";
const CORAL_DEEP = "#C8441F";
const AMBER = "#FFB74A";
const AMBER_LIGHT = "#FFE7B8";
const INDIGO = "#5753C9";
const INDIGO_LIGHT = "#A9A5FF";
const INK = "#17161B";

const STOPS = [0, 0.22, 0.42, 0.62, 0.78, 1];
const SILK_LIGHT = [CORAL_SOFT, CORAL_MID, CORAL, AMBER, AMBER_LIGHT, INDIGO_LIGHT];
const SILK_DARK = [INK, "#2E2A5C", INDIGO, CORAL_DEEP, CORAL, "#3A1E22"];

/** Hero: a moving mesh gradient seen through fluted glass, rippling under the cursor. */
export function SilkShader({ dark, still, onReady, onUnavailable, className }: ShaderProps) {
  const colors = dark ? SILK_DARK : SILK_LIGHT;
  return (
    <Shader
      disableTelemetry
      className={className}
      onReady={onReady}
      onUnavailable={onUnavailable}
    >
      <FilmGrain strength={dark ? 0.28 : 0.22} bias={1}>
        <CursorRipples intensity={still ? 0 : 6} decay={8} radius={0.45} chromaticSplit={0.6}>
          <FlutedGlass
            shape="bars"
            frequency={13}
            softness={0.6}
            waveAmplitude={0.04}
            waveFrequency={1.2}
            speed={still ? 0 : 0.12}
            refraction={1.6}
            aberration={0.25}
            highlight={dark ? 0.2 : 0.35}
            highlightSoftness={0.45}
            lightAngle={25}
          >
            <MeshGradient
              stops={colors.map((color, i) => ({ color, position: STOPS[i] ?? 1 }))}
              colorSpace="oklab"
              count={6}
              smoothness={2.6}
              variation={0.5}
              swirl={0.55}
              drift={0.8}
              speed={still ? 0 : 1.6}
              seed={21}
            />
          </FlutedGlass>
        </CursorRipples>
      </FilmGrain>
    </Shader>
  );
}

/** Closing call to action: ink silk with coral and indigo currents. Always dark. */
export function InkShader({ still, onReady, onUnavailable, className }: ShaderProps) {
  return (
    <Shader
      disableTelemetry
      className={className}
      onReady={onReady}
      onUnavailable={onUnavailable}
    >
      <FilmGrain strength={0.28} bias={2}>
        <FlowingGradient
          colorA={INK}
          colorB={INDIGO}
          colorC={CORAL}
          colorD={AMBER}
          colorSpace="oklch"
          distortion={0.7}
          speed={still ? 0 : 0.9}
          seed={5}
        />
      </FilmGrain>
    </Shader>
  );
}
