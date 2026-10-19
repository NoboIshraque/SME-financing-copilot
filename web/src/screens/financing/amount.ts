import { toAsciiDigits } from "../../api/format";

/** "2,00,000" or "২০০০০০" -> "200000.00"; null when it is not a positive taka amount. */
export function parseAmount(raw: string): string | null {
  const cleaned = toAsciiDigits(raw).replace(/[,\s৳]/g, "");
  if (!/^\d+(\.\d{1,2})?$/.test(cleaned) || !/[1-9]/.test(cleaned)) return null;
  const [int = "0", frac = ""] = cleaned.split(".");
  return `${int.replace(/^0+(?=\d)/, "")}.${frac.padEnd(2, "0")}`;
}
