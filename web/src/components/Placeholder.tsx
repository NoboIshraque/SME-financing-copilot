import { useTranslation } from "react-i18next";

import type { Screen } from "./AppShell";

/** Stand-in for a screen WP-14 has not built yet. */
export function Placeholder({ screen }: { screen: Screen }) {
  const { t } = useTranslation();
  return (
    <section aria-labelledby={`h-${screen}`}>
      <h2 id={`h-${screen}`} className="mb-2 text-xl font-semibold">
        {t(`nav.${screen}`)}
      </h2>
      <p className="text-slate-600">{t("common.comingSoon")}</p>
    </section>
  );
}
