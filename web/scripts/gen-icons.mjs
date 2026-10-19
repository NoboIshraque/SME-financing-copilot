// Generate the PWA icons (public/pwa-*.png) from the favicon's "H" mark, with no image tools:
// draws into an RGBA buffer and writes PNG with node:zlib. Deterministic; run `node scripts/gen-icons.mjs`.
import { writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { deflateSync } from "node:zlib";

const here = dirname(fileURLToPath(import.meta.url));
const TEAL = [0x0f, 0x76, 0x6e];
const WHITE = [0xff, 0xff, 0xff];

const CRC_TABLE = Array.from({ length: 256 }, (_, n) => {
  let c = n;
  for (let k = 0; k < 8; k += 1) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
  return c >>> 0;
});

function crc32(buffer) {
  let crc = 0xffffffff;
  for (const byte of buffer) crc = CRC_TABLE[(crc ^ byte) & 0xff] ^ (crc >>> 8);
  return (crc ^ 0xffffffff) >>> 0;
}

function chunk(type, data) {
  const length = Buffer.alloc(4);
  length.writeUInt32BE(data.length);
  const body = Buffer.concat([Buffer.from(type, "ascii"), data]);
  const crc = Buffer.alloc(4);
  crc.writeUInt32BE(crc32(body));
  return Buffer.concat([length, body, crc]);
}

function png(size, pixel) {
  const rows = [];
  for (let y = 0; y < size; y += 1) {
    const row = Buffer.alloc(1 + size * 4);
    for (let x = 0; x < size; x += 1) row.set(pixel(x, y), 1 + x * 4);
    rows.push(row);
  }
  const header = Buffer.alloc(13);
  header.writeUInt32BE(size, 0);
  header.writeUInt32BE(size, 4);
  header.set([8, 6, 0, 0, 0], 8);
  return Buffer.concat([
    Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]),
    chunk("IHDR", header),
    chunk("IDAT", deflateSync(Buffer.concat(rows), { level: 9 })),
    chunk("IEND", Buffer.alloc(0)),
  ]);
}

// The favicon's "H" in its 32-unit grid: two bars and a crossbar.
function inH(u, v) {
  const leftBar = u >= 9 && u <= 12 && v >= 9 && v <= 23;
  const rightBar = u >= 20 && u <= 23 && v >= 9 && v <= 23;
  const crossbar = u >= 12 && u <= 20 && v >= 14.5 && v <= 17.5;
  return leftBar || rightBar || crossbar;
}

function inRoundedSquare(u, v, radius) {
  const cx = Math.min(Math.max(u, radius), 32 - radius);
  const cy = Math.min(Math.max(v, radius), 32 - radius);
  return (u - cx) ** 2 + (v - cy) ** 2 <= radius ** 2;
}

/** 4x4 supersampled icon. `maskable`: full-bleed background, mark shrunk into the safe zone. */
function icon(size, maskable) {
  const samples = 4;
  return png(size, (x, y) => {
    let cover = 0;
    let mark = 0;
    for (let sy = 0; sy < samples; sy += 1) {
      for (let sx = 0; sx < samples; sx += 1) {
        const u = ((x + (sx + 0.5) / samples) / size) * 32;
        const v = ((y + (sy + 0.5) / samples) / size) * 32;
        const inside = maskable || inRoundedSquare(u, v, 7);
        if (!inside) continue;
        cover += 1;
        const scale = maskable ? 0.7 : 1;
        if (inH(16 + (u - 16) / scale, 16 + (v - 16) / scale)) mark += 1;
      }
    }
    const total = samples * samples;
    if (cover === 0) return [0, 0, 0, 0];
    const t = mark / cover;
    const rgb = TEAL.map((c, i) => Math.round(c + (WHITE[i] - c) * t));
    return [...rgb, Math.round((cover / total) * 255)];
  });
}

for (const [name, size, maskable] of [
  ["pwa-192.png", 192, false],
  ["pwa-512.png", 512, false],
  ["pwa-maskable-512.png", 512, true],
]) {
  writeFileSync(resolve(here, "../public", name), icon(size, maskable));
  console.log(`wrote public/${name}`);
}
