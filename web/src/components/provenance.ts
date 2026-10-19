// What the provenance drawer shows, and the hook number buttons use to open it.
import { createContext, useContext } from "react";

import type { DataMode, Figure, Provenance } from "../api/contracts";

export interface Explainable {
  /** Translated label, e.g. "Cash now". */
  label: string;
  /** The number exactly as it was shown. */
  shown: string;
  /** A figure is explained by GET /api/explain/{id}; its own provenance is the fallback. */
  figure?: Figure;
  /** Provenance known without a figure id, e.g. a source row or a forecast band. */
  provenance?: Provenance;
  dataMode?: DataMode;
}

export const ProvenanceContext = createContext<(item: Explainable) => void>(() => undefined);

export function useExplain(): (item: Explainable) => void {
  return useContext(ProvenanceContext);
}
