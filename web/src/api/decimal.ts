// Exact decimal-string arithmetic for display. Amounts, rates and probabilities arrive from the
// API as strings and are never turned into floats to be shown (charts convert only for pixels).
const DECIMAL = /^-?\d+(\.\d+)?$/;

interface Parts {
  negative: boolean;
  int: string;
  frac: string;
}

function parts(value: string): Parts {
  const trimmed = value.trim();
  if (!DECIMAL.test(trimmed)) throw new Error(`not a decimal: ${value}`);
  const negative = trimmed.startsWith("-");
  const [int = "0", frac = ""] = trimmed.replace("-", "").split(".");
  return { negative, int: int.replace(/^0+(?=\d)/, ""), frac };
}

function build(negative: boolean, int: string, frac: string): string {
  const body = (int.replace(/^0+(?=\d)/, "") || "0") + (frac ? `.${frac}` : "");
  return negative && /[1-9]/.test(body) ? `-${body}` : body;
}

export function isDecimal(value: string): boolean {
  return DECIMAL.test(value.trim());
}

/** Multiply by 10^places by moving the point: shiftDecimal("0.345", 2) === "34.5". */
export function shiftDecimal(value: string, places: number): string {
  const { negative, int, frac } = parts(value);
  let digits = int + frac;
  let point = int.length + places;
  if (point <= 0) {
    digits = "0".repeat(1 - point) + digits;
    point = 1;
  }
  if (point > digits.length) digits += "0".repeat(point - digits.length);
  return build(negative, digits.slice(0, point), digits.slice(point).replace(/0+$/, ""));
}

function increment(digits: string): string {
  const out = digits.split("");
  for (let i = out.length - 1; i >= 0; i -= 1) {
    if (out[i] === "9") {
      out[i] = "0";
    } else {
      out[i] = String(Number(out[i]) + 1);
      return out.join("");
    }
  }
  return `1${out.join("")}`;
}

/** Round half away from zero to exactly `places` decimals, digit by digit. */
export function roundDecimal(value: string, places: number): string {
  const { negative, int, frac } = parts(value);
  const kept = (frac + "0".repeat(places)).slice(0, places);
  let digits = int + kept;
  if ((frac.charAt(places) || "0") >= "5") digits = increment(digits);
  const intLength = digits.length - places;
  return build(negative, digits.slice(0, intLength) || "0", digits.slice(intLength));
}

/** Drop trailing fraction zeros: "13.50" -> "13.5", "2.00" -> "2". */
export function trimZeros(value: string): string {
  const { negative, int, frac } = parts(value);
  return build(negative, int, frac.replace(/0+$/, ""));
}

/** -1, 0 or 1, comparing exactly. */
export function compareDecimal(a: string, b: string): -1 | 0 | 1 {
  const x = parts(trimZeros(a));
  const y = parts(trimZeros(b));
  if (x.negative !== y.negative) return x.negative ? -1 : 1;
  const sign = x.negative ? -1 : 1;
  if (x.int.length !== y.int.length) return (x.int.length > y.int.length ? sign : -sign) as -1 | 1;
  const width = Math.max(x.frac.length, y.frac.length);
  const left = x.int + x.frac.padEnd(width, "0");
  const right = y.int + y.frac.padEnd(width, "0");
  if (left === right) return 0;
  return (left > right ? sign : -sign) as -1 | 1;
}

/** For chart geometry only: a pixel position, never a displayed value. */
export function toChartNumber(value: string): number {
  return Number(value);
}
