"use client";

import { useTheme } from "next-themes";
import dynamic from "next/dynamic";
import { type ComponentType, useState, useSyncExternalStore } from "react";

import type { ShaderProps } from "@/components/home/landing-shaders";
import { cn } from "@/lib/utils";

/**
 * Animated backdrops for the logged-out home page (ADR 0037). The CSS fallback (`.landing-silk`
 * / `.landing-ink` in globals.css) paints with the server HTML; the WebGPU canvas is loaded
 * lazily and fades in once the GPU is ready. Browsers without WebGPU never download it (the
 * library is ~730 KB gzipped) and keep the fallback. Reduced motion freezes the animation.
 */

const SilkShader = dynamic(() => import("@/components/home/landing-shaders").then((m) => m.SilkShader), {
  ssr: false,
});
const InkShader = dynamic(() => import("@/components/home/landing-shaders").then((m) => m.InkShader), {
  ssr: false,
});

const SCENES = { silk: SilkShader, ink: InkShader } as const;

const QUERY = "(prefers-reduced-motion: reduce)";

function useReducedMotion(): boolean {
  return useSyncExternalStore(
    (onChange) => {
      const media = window.matchMedia(QUERY);
      media.addEventListener("change", onChange);
      return () => media.removeEventListener("change", onChange);
    },
    () => window.matchMedia(QUERY).matches,
    () => false,
  );
}

const noop = () => () => {};

/** Whether the browser has WebGPU. False on the server and during hydration. */
function useWebGpu(): boolean {
  return useSyncExternalStore(
    noop,
    () => "gpu" in navigator,
    () => false,
  );
}

export function LandingBackdrop({
  scene,
  className,
}: {
  scene: keyof typeof SCENES;
  className?: string;
}) {
  const gpu = useWebGpu();
  const { resolvedTheme } = useTheme();
  const still = useReducedMotion();
  const [ready, setReady] = useState(false);
  const [unavailable, setUnavailable] = useState(false);
  const Scene: ComponentType<ShaderProps> = SCENES[scene];
  return (
    <div aria-hidden className={cn("pointer-events-none", `landing-${scene}`, className)}>
      {gpu && resolvedTheme && !unavailable && (
        <Scene
          dark={resolvedTheme === "dark"}
          still={still}
          onReady={() => setReady(true)}
          onUnavailable={() => setUnavailable(true)}
          className={cn(
            "size-full transition-opacity duration-1000",
            ready ? "opacity-100" : "opacity-0",
          )}
        />
      )}
    </div>
  );
}
