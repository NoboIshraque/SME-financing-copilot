// Money and number formatting without floats: amounts arrive from the API as exact strings.
import type { Language } from "../i18n";
import type { Currency } from "./contracts";
import { compareDecimal, roundDecimal, shiftDecimal, trimZeros } from "./decimal";

const BANGLA_DIGITS = ["০", "১", "২", "৩", "৪", "৫", "৬", "৭", "৮", "৯"];

export function toBanglaDigits(text: string): string {
  return text.replace(/[0-9]/g, (d) => BANGLA_DIGITS[Number(d)] ?? d);
}

/** Bangla (০-৯) and full-width (０-９, from Chinese IMEs) digits to ASCII, for codes users type. */
export function toAsciiDigits(text: string): string {
  return text
    .replace(/[০-৯]/g, (d) => String(d.charCodeAt(0) - 0x09e6))
    .replace(/[０-９]/g, (d) => String(d.charCodeAt(0) - 0xff10));
}

/** Group an integer string the South Asian way (12,34,567) or the Western way (1,234,567). */
export function groupDigits(integer: string, style: "south_asian" | "western"): string {
  if (integer.length <= 3) return integer;
  const last3 = integer.slice(-3);
  const rest = integer.slice(0, -3);
  if (style === "western") {
    return rest.replace(/\B(?=(\d{3})+(?!\d))/g, ",") + "," + last3;
  }
  return rest.replace(/\B(?=(\d{2})+(?!\d))/g, ",") + "," + last3;
}

const DECIMAL = /^-?\d+(\.\d+)?$/;
const SYMBOLS: Record<Currency, string> = { BDT: "৳", USD: "$", CNY: "¥" };

/** Format a decimal-string amount for the given language. Never uses floats. */
export function formatMoney(
  amount: string,
  currency: Currency,
  language: Language,
  opts: { paisa?: boolean } = {},
): string {
  const trimmed = amount.trim();
  if (!DECIMAL.test(trimmed)) throw new Error(`not a decimal amount: ${amount}`);
  const negative = trimmed.startsWith("-");
  const [intPart = "0", fracPart = ""] = trimmed.replace("-", "").split(".");
  const integer = intPart.replace(/^0+(?=\d)/, "");
  const grouped = groupDigits(integer, language === "zh" || currency !== "BDT" ? "western" : "south_asian");
  const fraction = opts.paisa ? "." + (fracPart + "00").slice(0, 2) : "";
  let body = `${grouped}${fraction}`;
  if (language === "bn") body = toBanglaDigits(body);
  const sign = negative && /[1-9]/.test(intPart + fracPart) ? "-" : "";
  return `${sign}${SYMBOLS[currency]}${body}`;
}

/** Format a decimal-string amount in taka for the given language. Never uses floats. */
export function formatTaka(amount: string, language: Language, opts: { paisa?: boolean } = {}): string {
  return formatMoney(amount, "BDT", language, opts);
}

/** A plain number, rounded half away from zero, grouped and in the language's digits. */
export function formatNumber(value: string, language: Language, maxFraction = 2): string {
  const rounded = trimZeros(roundDecimal(value, maxFraction));
  const negative = rounded.startsWith("-");
  const [int = "0", frac] = rounded.replace("-", "").split(".");
  let body = groupDigits(int, language === "zh" ? "western" : "south_asian") + (frac ? `.${frac}` : "");
  if (language === "bn") body = toBanglaDigits(body);
  return `${negative ? "-" : ""}${body}`;
}

/** "13.62" -> "13.6%"; with `probability`, "0.34" -> "34%". */
export function formatPercent(
  value: string,
  language: Language,
  opts: { probability?: boolean; maxFraction?: number } = {},
): string {
  const percent = opts.probability ? shiftDecimal(value, 2) : value;
  return `${formatNumber(percent, language, opts.maxFraction ?? 1)}%`;
}

const LOCALES: Record<Language, string> = { en: "en-GB", bn: "bn-BD", zh: "zh-CN" };
const DATE_STYLES: Record<"short" | "long" | "weekday", Intl.DateTimeFormatOptions> = {
  short: { day: "numeric", month: "short" },
  long: { day: "numeric", month: "long", year: "numeric" },
  weekday: { weekday: "long", day: "numeric", month: "long", year: "numeric" },
};

/** A calendar date (YYYY-MM-DD), read in UTC so no timezone can shift the day. */
export function formatDate(iso: string, language: Language, style: keyof typeof DATE_STYLES = "short"): string {
  const date = new Date(`${iso.slice(0, 10)}T00:00:00Z`);
  return new Intl.DateTimeFormat(LOCALES[language], { ...DATE_STYLES[style], timeZone: "UTC" }).format(date);
}

/** A moment in time, shown in Dhaka time. */
export function formatDateTime(iso: string, language: Language): string {
  return new Intl.DateTimeFormat(LOCALES[language], {
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
    timeZone: "Asia/Dhaka",
  }).format(new Date(iso));
}

/** Short amounts for chart axes: lakh/crore in English and Bangla, 万 in Chinese. */
export function formatCompactTaka(amount: string, language: Language): string {
  const negative = amount.trim().startsWith("-") && /[1-9]/.test(amount);
  const abs = amount.trim().replace("-", "");
  const steps: Array<[string, number, Record<Language, string>]> =
    language === "zh"
      ? [["10000", 4, { en: "", bn: "", zh: "万" }]]
      : [
          ["10000000", 7, { en: " Cr", bn: " কোটি", zh: "" }],
          ["100000", 5, { en: " L", bn: " লাখ", zh: "" }],
          ["1000", 3, { en: "K", bn: " হাজার", zh: "" }],
        ];
  for (const [threshold, places, suffix] of steps) {
    if (compareDecimal(abs, threshold) >= 0) {
      return `${negative ? "-" : ""}৳${formatNumber(shiftDecimal(abs, -places), language, 1)}${suffix[language]}`;
    }
  }
  return `${negative ? "-" : ""}৳${formatNumber(abs, language, 0)}`;
}
