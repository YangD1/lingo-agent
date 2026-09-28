import type { NextConfig } from "next";

// Browser -> Next (same origin) -> backend, so the httpOnly auth cookie is sent
// automatically and no CORS is needed (ADR 0003). Rewrites are resolved at
// `next build` time, so BACKEND_URL must be set when building, not only at runtime.
const backendUrl = process.env.BACKEND_URL ?? "http://localhost:8000";

const nextConfig: NextConfig = {
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${backendUrl}/:path*` }];
  },
};

export default nextConfig;
