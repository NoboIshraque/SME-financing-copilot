// Every number on every screen is a button that opens its provenance (N13): FigureValue for
// engine figures, Num for numbers whose provenance is known without a figure id.
import { useTranslation } from "react-i18next";

import type { DataMode, Figure, Provenance, Unit } from "../api/contracts";
import { useServerText } from "../i18n/serverText";
import { useFormat } from "../i18n/useFormat";
import { useExplain, type Explainable } from "./provenance";

const BUTTON =
  "tabular-nums underline decoration-dotted decoration-1 underline-offset-4 hover:decoration-solid focus-visible:rounded focus-visible:outline focus-visible:outline-2 focus-visible:outline-teal-600";

function NumberButton({ item, className }: { item: Explainable; className: string }) {
  const { t } = useTranslation();
  const explain = useExplain();
  return (
    <button
      type="button"
      onClick={() => explain(item)}
      aria-haspopup="dialog"
      aria-label={t("provenance.open", { label: item.label, value: item.shown })}
      className={`${BUTTON} ${className}`}
      data-figure-id={item.figure?.id}
    >
      {item.shown}
    </button>
  );
}

export function FigureValue({ figure, className = "" }: { figure: Figure; className?: string }) {
  const format = useFormat();
  const text = useServerText();
  const shown = format.value(figure.value, figure.unit);
  return <NumberButton item={{ label: text(figure.label_key), shown, figure }} className={className} />;
}

interface NumProps {
  value: string;
  unit: Unit;
  label: string;
  provenance: Provenance;
  dataMode?: DataMode;
  className?: string;
}

export function Num({ value, unit, label, provenance, dataMode, className = "" }: NumProps) {
  const format = useFormat();
  return <NumberButton item={{ label, shown: format.value(value, unit), provenance, dataMode }} className={className} />;
}
