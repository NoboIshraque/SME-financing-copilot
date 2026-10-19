// Formatting bound to the current UI language. Every displayed number goes through here.
import { useTranslation } from "react-i18next";

import type { Money, Unit } from "../api/contracts";
import { formatDate, formatDateTime, formatMoney, formatNumber, formatPercent } from "../api/format";
import type { Language } from ".";

/** Paisa are shown only when there are some: ৳4,27,842 but ৳57.70. */
function withPaisa(amount: string): boolean {
  return /\.\d*[1-9]/.test(amount);
}

export function useFormat() {
  const { t, i18n } = useTranslation();
  const lang = (i18n.language || "en") as Language;

  const days = (value: string | number) => {
    const text = String(value);
    // Number() only picks the plural form; the shown digits come from the exact string.
    return t("unit.days", { count: Number(text), value: formatNumber(text, lang, 1) });
  };

  const value = (raw: string, unit: Unit): string => {
    switch (unit) {
      case "BDT":
      case "USD":
      case "CNY":
        return formatMoney(raw, unit, lang, { paisa: withPaisa(raw) });
      case "percent":
        return formatPercent(raw, lang, { maxFraction: 2 });
      case "probability":
        return formatPercent(raw, lang, { probability: true });
      case "days":
        return days(raw);
      case "count":
        return formatNumber(raw, lang, 0);
      case "ratio":
      case "score":
        return formatNumber(raw, lang, 2);
    }
  };

  return {
    lang,
    days,
    value,
    money: (money: Money) => formatMoney(money.amount, money.currency ?? "BDT", lang, { paisa: withPaisa(money.amount) }),
    number: (raw: string, maxFraction?: number) => formatNumber(raw, lang, maxFraction),
    percent: (raw: string) => formatPercent(raw, lang, { maxFraction: 2 }),
    probability: (raw: string) => formatPercent(raw, lang, { probability: true }),
    date: (iso: string, style?: "short" | "long" | "weekday") => formatDate(iso, lang, style),
    dateTime: (iso: string) => formatDateTime(iso, lang),
  };
}
