// 6-digit TOTP input. Accepts Bangla and full-width digits; `normalizeCode` turns them into ASCII.
import { toAsciiDigits } from "../api/format";

/** The 6 ASCII digits of a typed code, or null when it is not exactly 6 digits. */
export function normalizeCode(raw: string): string | null {
  const digits = toAsciiDigits(raw).replace(/[\s-]/g, "");
  return /^\d{6}$/.test(digits) ? digits : null;
}

interface CodeFieldProps {
  id: string;
  label: string;
  value: string;
  onChange: (value: string) => void;
  describedBy?: string;
  invalid?: boolean;
}

export function CodeField({ id, label, value, onChange, describedBy, invalid }: CodeFieldProps) {
  return (
    <div>
      <label htmlFor={id} className="mb-1 block text-sm font-medium">
        {label}
      </label>
      <input
        id={id}
        data-autofocus
        value={value}
        onChange={(event) => onChange(event.target.value)}
        inputMode="numeric"
        autoComplete="one-time-code"
        maxLength={9}
        aria-describedby={describedBy}
        aria-invalid={invalid || undefined}
        className="w-full rounded-xl border border-slate-300 bg-white px-3 py-3 text-center font-mono text-2xl tracking-[0.4em] dark:border-slate-600 dark:bg-slate-800"
      />
    </div>
  );
}
