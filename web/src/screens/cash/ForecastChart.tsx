// 13-week balance chart: P10-P90 band, likely (P50) line, safety buffer, gap markers and an
// optional what-if line. The chart is visual only; the table under it carries every number.
import { useSyncExternalStore } from "react";
import { useTranslation } from "react-i18next";
import {
  Area,
  CartesianGrid,
  ComposedChart,
  Line,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import type { CashGap, ForecastBand } from "../../api/contracts";
import { toChartNumber } from "../../api/decimal";
import { formatCompactTaka } from "../../api/format";
import { useFormat } from "../../i18n/useFormat";

interface Row {
  day: string;
  low: number;
  range: number;
  likely: number;
  whatIf?: number;
  p10: string;
  p50: string;
  p90: string;
}

function canMeasure(): boolean {
  return typeof ResizeObserver !== "undefined";
}

function BandTooltip({ active, payload }: { active?: boolean; payload?: ReadonlyArray<{ payload?: unknown }> }) {
  const { t } = useTranslation();
  const format = useFormat();
  const row = payload?.[0]?.payload as Row | undefined;
  if (!active || !row) return null;
  return (
    <div className="rounded-lg bg-white p-2 text-xs shadow ring-1 ring-slate-200 dark:bg-slate-900 dark:ring-slate-700">
      <p className="font-semibold">{format.date(row.day, "long")}</p>
      <p>{t("cash.p90")}: {format.money({ amount: row.p90 })}</p>
      <p className="font-semibold">{t("cash.p50")}: {format.money({ amount: row.p50 })}</p>
      <p>{t("cash.p10")}: {format.money({ amount: row.p10 })}</p>
    </div>
  );
}

export function ForecastChart({ band, whatIf, gaps }: { band: ForecastBand; whatIf?: ForecastBand; gaps: CashGap[] }) {
  const { t } = useTranslation();
  const format = useFormat();
  const measurable = useSyncExternalStore(() => () => undefined, canMeasure, () => false);
  if (!measurable) return null;

  const rows: Row[] = band.points.map((point, i) => {
    const low = toChartNumber(point.p10.amount);
    const shocked = whatIf?.points[i];
    return {
      day: point.day,
      low,
      range: toChartNumber(point.p90.amount) - low,
      likely: toChartNumber(point.p50.amount),
      whatIf: shocked ? toChartNumber(shocked.p50.amount) : undefined,
      p10: point.p10.amount,
      p50: point.p50.amount,
      p90: point.p90.amount,
    };
  });

  return (
    <div className="h-72 w-full text-slate-500 dark:text-slate-400" aria-hidden="true">
      <ResponsiveContainer>
        <ComposedChart data={rows} margin={{ top: 12, right: 8, bottom: 0, left: 0 }} accessibilityLayer={false}>
          <CartesianGrid strokeDasharray="3 3" stroke="currentColor" strokeOpacity={0.15} />
          <XAxis dataKey="day" tickFormatter={(day: string) => format.date(day)} interval={13} tick={{ fontSize: 11, fill: "currentColor" }} />
          <YAxis
            width={70}
            tick={{ fontSize: 11, fill: "currentColor" }}
            tickFormatter={(value: number) => formatCompactTaka(String(Math.round(value)), format.lang)}
          />
          <Tooltip content={(props) => <BandTooltip active={props.active} payload={props.payload} />} />
          <Area dataKey="low" stackId="band" stroke="none" fill="transparent" isAnimationActive={false} />
          <Area dataKey="range" stackId="band" stroke="none" fill="#14b8a6" fillOpacity={0.2} isAnimationActive={false} />
          <Line dataKey="likely" stroke="#0f766e" strokeWidth={2.5} dot={false} isAnimationActive={false} />
          {whatIf && <Line dataKey="whatIf" stroke="#d97706" strokeWidth={2} strokeDasharray="6 4" dot={false} isAnimationActive={false} />}
          <ReferenceLine y={toChartNumber(band.buffer.amount)} stroke="#dc2626" strokeDasharray="4 4" label={{ value: t("cash.bufferLine"), position: "insideTopLeft", fontSize: 11, fill: "#dc2626" }} />
          {gaps.map((gap) => (
            <ReferenceLine key={gap.first_breach_day} x={gap.first_breach_day} stroke="#dc2626" strokeWidth={2} label={{ value: "!", position: "top", fill: "#dc2626" }} />
          ))}
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}
