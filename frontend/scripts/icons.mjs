// Generate the PNG app icons from the Scholaris SVG mark.
// Run once (and after any logo change):  npm run icons
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import sharp from "sharp";

const scriptDir = dirname(fileURLToPath(import.meta.url));
const publicDir = join(scriptDir, "..", "public");

const rounded = readFileSync(join(publicDir, "favicon.svg"));

// Maskable icons must fill the whole square (the OS crops them), with the mark
// kept inside the ~80% safe zone.
const maskable = Buffer.from(`
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" width="64" height="64">
  <defs>
    <linearGradient id="g" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="#6366f1" />
      <stop offset="1" stop-color="#8b5cf6" />
    </linearGradient>
  </defs>
  <rect width="64" height="64" fill="url(#g)" />
  <path d="M32 12 L36.4 27.6 L52 32 L36.4 36.4 L32 52 L27.6 36.4 L12 32 L27.6 27.6 Z" fill="#ffffff" />
</svg>
`);

const jobs = [
  { source: rounded, size: 192, out: "icons/icon-192.png" },
  { source: rounded, size: 512, out: "icons/icon-512.png" },
  { source: maskable, size: 512, out: "icons/icon-maskable-512.png" },
  { source: maskable, size: 180, out: "apple-touch-icon.png" },
];

for (const job of jobs) {
  await sharp(job.source, { density: 384 })
    .resize(job.size, job.size)
    .png()
    .toFile(join(publicDir, job.out));
  console.log(`wrote public/${job.out} (${job.size}x${job.size})`);
}
