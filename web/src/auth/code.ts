import { toAsciiDigits } from "../api/format";

/** The 6 ASCII digits of a typed TOTP code (Bangla and full-width digits accepted), or null. */
export function normalizeCode(raw: string): string | null {
  const digits = toAsciiDigits(raw).replace(/[\s-]/g, "");
  return /^\d{6}$/.test(digits) ? digits : null;
}
