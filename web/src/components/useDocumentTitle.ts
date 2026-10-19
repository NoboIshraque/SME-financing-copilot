import { useEffect } from "react";
import { useTranslation } from "react-i18next";

/** "Cash · DecisionGuard": every screen names itself in the browser tab (WCAG 2.4.2). */
export function useDocumentTitle(title: string): void {
  const { t } = useTranslation();
  const appName = t("app.name");
  useEffect(() => {
    document.title = `${title} · ${appName}`;
  }, [title, appName]);
}
