// Loading, error and empty states shared by every screen.
import type { UseQueryResult } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { describeError, useServerText } from "../i18n/serverText";
import { Icon } from "./Icon";

export function LoadingState() {
  const { t } = useTranslation();
  return (
    <div aria-busy="true" className="animate-pulse rounded-2xl bg-white p-6 text-slate-500 dark:bg-slate-900 dark:text-slate-400">
      {t("common.loading")}
    </div>
  );
}

export function ErrorState({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const { t } = useTranslation();
  const text = useServerText();
  const { key, values } = describeError(error);
  return (
    <div role="alert" className="rounded-2xl border border-red-200 bg-red-50 p-4 text-red-900 dark:border-red-900 dark:bg-red-950 dark:text-red-100">
      <p className="flex items-start gap-2">
        <Icon name="alert" className="mt-0.5 h-5 w-5 shrink-0" />
        <span>{text(key, values)}</span>
      </p>
      {onRetry && (
        <button
          type="button"
          onClick={onRetry}
          className="mt-3 rounded-lg border border-red-300 px-3 py-1.5 text-sm font-medium hover:bg-red-100 dark:border-red-800 dark:hover:bg-red-900"
        >
          {t("common.retry")}
        </button>
      )}
    </div>
  );
}

export function EmptyState({ children }: { children: ReactNode }) {
  return (
    <div className="rounded-2xl border border-dashed border-slate-300 p-6 text-center text-slate-600 dark:border-slate-700 dark:text-slate-400">
      {children}
    </div>
  );
}

/** Render a query: loading, error with retry, an empty state, or the data. */
export function QueryView<T>({
  query,
  isEmpty,
  empty,
  children,
}: {
  query: UseQueryResult<T>;
  isEmpty?: (data: T) => boolean;
  empty?: ReactNode;
  children: (data: T) => ReactNode;
}) {
  if (query.isPending) return <LoadingState />;
  if (query.isError) return <ErrorState error={query.error} onRetry={() => void query.refetch()} />;
  if (isEmpty?.(query.data)) return <EmptyState>{empty}</EmptyState>;
  return <>{children(query.data)}</>;
}
