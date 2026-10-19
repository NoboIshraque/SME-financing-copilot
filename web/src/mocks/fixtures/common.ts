// Building blocks for mock fixtures. All synthetic; ids and source rows mirror the WP-00 universe
// (data/synthetic/universe/sme_grocery) so mock screens tell the same story as the real data.
import type { Figure, Money, Provenance, Unit } from "../../api/contracts";

export const TENANT = "sme_grocery";
export const AS_OF = "2026-09-30";
export const NOW = "2026-09-30T18:00:00Z";
export const SEED = 20261020;

export function money(amount: number | string): Money {
  return { amount: typeof amount === "number" ? `${amount}.00` : amount, currency: "BDT" };
}

/** ISO date `days` after AS_OF. */
export function dayAfterAsOf(days: number): string {
  const date = new Date(`${AS_OF}T00:00:00Z`);
  date.setUTCDate(date.getUTCDate() + days);
  return date.toISOString().slice(0, 10);
}

export function figure(
  id: string,
  labelKey: string,
  value: string,
  unit: Unit,
  provenance: Partial<Provenance> & { formula_id: string },
): Figure {
  return {
    id,
    label_key: labelKey,
    value,
    unit,
    data_mode: "synthetic",
    provenance: { formula_version: 1, input_fact_ids: [], source_row_ids: [], ...provenance },
  };
}
