// Decision stability (N16): how often the advice held across stress and noise variations, which
// variations would flip it, and a loud flag when irrelevant noise changed the answer.
import { useTranslation } from "react-i18next";

import type { StabilityReport } from "../api/contracts";
import { shiftDecimal, toChartNumber } from "../api/decimal";
import { useServerText } from "../i18n/serverText";
import { useFormat } from "../i18n/useFormat";

export function StabilityBar({ report }: { report: StabilityReport }) {
  const { t } = useTranslation();
  const text = useServerText();
  const format = useFormat();
  const held = report.results.filter((result) => result.held).length;
  const noiseFlips = report.results.filter((result) => result.kind === "noise" && !result.held);
  const width = Math.max(0, Math.min(100, toChartNumber(shiftDecimal(report.score, 2))));
  return (
    <div className="space-y-2">
      <div className="flex items-baseline justify-between gap-2">
        <p className="font-medium">{t("stability.holds", { held, total: report.results.length })}</p>
        <p className="text-lg font-semibold tabular-nums">{format.probability(report.score)}</p>
      </div>
      <div
        role="meter"
        aria-label={t("stability.label")}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={width}
        aria-valuetext={format.probability(report.score)}
        className="h-3 rounded-full bg-slate-200 dark:bg-slate-700"
      >
        <div className={`h-3 rounded-full ${width >= 80 ? "bg-emerald-600" : width >= 50 ? "bg-amber-500" : "bg-red-600"}`} style={{ width: `${width}%` }} />
      </div>
      {noiseFlips.length > 0 && (
        <p role="alert" className="rounded-lg bg-red-50 p-2 text-sm font-medium text-red-900 dark:bg-red-950 dark:text-red-100">
          {t("stability.unreliable", { names: noiseFlips.map((flip) => text(`variation.${flip.name}`)).join(", ") })}
        </p>
      )}
      {report.what_would_flip && report.what_would_flip.length > 0 && (
        <div>
          <p className="text-sm font-medium">{t("stability.wouldFlip")}</p>
          <ul className="mt-1 list-disc pl-5 text-sm">
            {report.what_would_flip.map((name) => (
              <li key={name}>{text(`variation.${name}`)}</li>
            ))}
          </ul>
        </div>
      )}
      <details className="text-sm">
        <summary className="cursor-pointer text-teal-800 dark:text-teal-300">{t("stability.allVariations")}</summary>
        <ul className="mt-1 space-y-0.5">
          {report.results.map((result) => (
            <li key={result.name} className="flex justify-between gap-2">
              <span>
                {text(`variation.${result.name}`)} <span className="text-slate-500">({t(`stability.kind.${result.kind}`)})</span>
              </span>
              <span className={result.held ? "text-emerald-700 dark:text-emerald-300" : "text-red-700 dark:text-red-300"}>
                {result.held ? t("stability.held") : t("stability.flipped")}
              </span>
            </li>
          ))}
        </ul>
      </details>
    </div>
  );
}
