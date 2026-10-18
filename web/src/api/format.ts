// Money and number formatting without floats: amounts arrive from the API as exact strings.
import type { Language } from "../i18n";

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

/** Format a decimal-string amount in taka for the given language. Never uses floats. */
export function formatTaka(amount: string, language: Language, opts: { paisa?: boolean } = {}): string {
  const trimmed = amount.trim();
  if (!DECIMAL.test(trimmed)) throw new Error(`not a decimal amount: ${amount}`);
  const negative = trimmed.startsWith("-");
  const [intPart = "0", fracPart = ""] = trimmed.replace("-", "").split(".");
  const integer = intPart.replace(/^0+(?=\d)/, "");
  const grouped = groupDigits(integer, language === "zh" ? "western" : "south_asian");
  const fraction = opts.paisa ? "." + (fracPart + "00").slice(0, 2) : "";
  let body = `${grouped}${fraction}`;
  if (language === "bn") body = toBanglaDigits(body);
  const sign = negative && /[1-9]/.test(intPart + fracPart) ? "-" : "";
  return `${sign}৳${body}`;
}
