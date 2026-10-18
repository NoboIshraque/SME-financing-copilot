// A number computed by an engine, shown in the current language. Every figure on every screen
// renders through this component, so its provenance (formula, inputs, source rows) can be
// opened from one place.
import type { Figure } from "../api/contracts";
import { useFormat } from "../i18n/useFormat";

export function FigureValue({ figure, className = "" }: { figure: Figure; className?: string }) {
  const format = useFormat();
  return (
    <span className={`tabular-nums ${className}`} data-figure-id={figure.id}>
      {format.value(figure.value, figure.unit)}
    </span>
  );
}
