import type { NextConfig } from "next";
import createNextIntlPlugin from "next-intl/plugin";

// Browser -> Next (same origin) -> backend, so the httpOnly auth cookie is sent
// automatically and no CORS is needed (ADR 0003). Rewrites are resolved at
// `next build` time, so BACKEND_URL must be set when building, not only at runtime.
const backendUrl = process.env.BACKEND_URL ?? "http://localhost:8000";

const nextConfig: NextConfig = {
  // Self-contained server (.next/standalone) for the Docker image: only the traced
  // node_modules are copied, keeping the image and its memory footprint small.
  output: "standalone",
  experimental: {
    // Build workers default to one per host core; cap them so `next build` fits on
    // small servers and doesn't balloon memory on many-core dev machines.
    cpus: Number(process.env.NEXT_BUILD_CPUS ?? 4),
  },
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${backendUrl}/:path*` }];
  },
};

// Reads src/i18n/request.ts (ADR 0006).
export default createNextIntlPlugin()(nextConfig);
