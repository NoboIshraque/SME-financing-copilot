// Generate src/api/contracts.ts from docs/api/contracts.json (the backend's frozen contracts).
// Run via `npm run contracts` at the repo root. Never edit contracts.ts by hand.
import { readFileSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { compile } from "json-schema-to-typescript";

const here = dirname(fileURLToPath(import.meta.url));
const source = resolve(here, "../../docs/api/contracts.json");
const target = resolve(here, "../src/api/contracts.ts");

const schema = JSON.parse(readFileSync(source, "utf8"));
const names = Object.keys(schema.$defs).sort();
const root = {
  title: "HishabContracts",
  type: "object",
  additionalProperties: false,
  properties: Object.fromEntries(names.map((n) => [n, { $ref: `#/$defs/${n}` }])),
  $defs: schema.$defs,
};

const banner = `/* Generated from docs/api/contracts.json (contracts v${schema.version}). Do not edit. */\n` +
  `/* Money amounts are decimal strings: never convert them to floats. */`;
const ts = await compile(root, "HishabContracts", {
  bannerComment: banner,
  additionalProperties: false,
  unreachableDefinitions: true,
  style: { semi: true, singleQuote: false, printWidth: 100 },
});
writeFileSync(target, ts + `\nexport const CONTRACTS_VERSION = "${schema.version}";\n`);
console.log(`wrote src/api/contracts.ts (${names.length} contracts, v${schema.version})`);
