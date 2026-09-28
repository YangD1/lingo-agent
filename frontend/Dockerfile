# Frontend image. Build context is ./frontend.
#
# BACKEND_URL is needed twice: at build time for the /api rewrites in next.config.ts
# (Next bakes rewrite targets into the build), and at runtime for server components
# that call the backend directly (src/lib/server-api.ts).

FROM node:24-slim AS base
ENV PNPM_HOME=/pnpm \
    PATH=/pnpm:$PATH \
    NEXT_TELEMETRY_DISABLED=1 \
    COREPACK_ENABLE_DOWNLOAD_PROMPT=0
RUN corepack enable
WORKDIR /app

# --- deps: install from the lockfile only, cached across source changes ---
FROM base AS deps
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
RUN --mount=type=cache,id=pnpm,target=/pnpm/store pnpm install --frozen-lockfile

# --- build ---
FROM base AS build
ARG BACKEND_URL=http://backend:8000
# Bounded build: heap cap + worker cap (next.config.ts). Measured peak ~1.4GiB.
ARG NEXT_BUILD_CPUS=4
ENV BACKEND_URL=$BACKEND_URL \
    NEXT_BUILD_CPUS=$NEXT_BUILD_CPUS \
    NODE_OPTIONS=--max-old-space-size=2048
COPY --from=deps /app/node_modules node_modules
COPY . .
# public/ may be absent in a fresh clone (git does not track empty directories).
RUN mkdir -p public && pnpm build

# --- runtime: standalone server, no pnpm or dev dependencies ---
FROM node:24-slim
ARG BACKEND_URL=http://backend:8000
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    BACKEND_URL=$BACKEND_URL \
    HOSTNAME=0.0.0.0 \
    PORT=3000
WORKDIR /app

COPY --from=build --chown=node:node /app/.next/standalone ./
COPY --from=build --chown=node:node /app/.next/static .next/static
COPY --from=build --chown=node:node /app/public public

USER node
EXPOSE 3000

HEALTHCHECK --interval=10s --timeout=3s --start-period=20s --retries=3 \
    CMD ["node", "-e", "fetch('http://127.0.0.1:3000/login').then(r=>process.exit(r.ok?0:1),()=>process.exit(1))"]

CMD ["node", "server.js"]
