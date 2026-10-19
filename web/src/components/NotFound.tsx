import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

import { useDocumentTitle } from "./useDocumentTitle";

export function NotFound() {
  const { t } = useTranslation();
  useDocumentTitle(t("common.notFound"));
  return (
    <section aria-labelledby="h-not-found" className="space-y-3">
      <h2 id="h-not-found" className="text-xl font-semibold">
        {t("common.notFound")}
      </h2>
      <p className="text-slate-600 dark:text-slate-400">{t("common.notFoundHelp")}</p>
      <Link to="/" className="inline-block text-teal-800 underline dark:text-teal-300">
        {t("common.goHome")}
      </Link>
    </section>
  );
}
