import type { Figure } from "./contracts";

/** The figure with this label_key, e.g. "cash.runway_days". */
export function findFigure(figures: readonly Figure[] | undefined, labelKey: string): Figure | undefined {
  return figures?.find((figure) => figure.label_key === labelKey);
}
