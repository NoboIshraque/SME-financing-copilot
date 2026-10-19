// Text for keys the server sends (title_key, message_key, label_key...) and for errors.
import { useTranslation } from "react-i18next";

import { ApiRequestError } from "../api/client";

/** "alert.gap_ahead" -> "Gap ahead": readable fallback for a key with no translation yet. */
export function humanizeKey(key: string): string {
  const last = (key.split(".").pop() ?? key).replace(/_/g, " ").trim();
  return last.charAt(0).toUpperCase() + last.slice(1);
}

/** Translate a server key; unknown keys read as words, never as a raw key. */
export function useServerText(): (key: string, values?: Record<string, string>) => string {
  const { t } = useTranslation();
  return (key, values) => t(key, { ...values, defaultValue: humanizeKey(key) });
}

/** The i18n key and values that describe an error from the API client. */
export function describeError(error: unknown): { key: string; values: Record<string, string> } {
  if (error instanceof ApiRequestError) {
    if (error.body) return { key: error.body.message_key, values: error.body.detail ?? {} };
    return { key: error.status >= 500 ? "error.server" : "common.error", values: {} };
  }
  return { key: "error.network", values: {} };
}
