// `pnpm start`: run the production build the same way the Docker image does.
// With `output: "standalone"`, `next start` is unsupported; the standalone server
// expects static assets and public/ next to it, which `next build` does not copy.
import { cpSync, existsSync, rmSync } from "node:fs";

const out = ".next/standalone";
if (!existsSync(`${out}/server.js`)) {
  console.error(`${out}/server.js not found; run \`pnpm build\` first`);
  process.exit(1);
}
rmSync(`${out}/.next/static`, { recursive: true, force: true });
cpSync(".next/static", `${out}/.next/static`, { recursive: true });
if (existsSync("public")) cpSync("public", `${out}/public`, { recursive: true });

// Honors PORT and HOSTNAME; chdirs into the standalone directory itself.
await import(`../${out}/server.js`);
