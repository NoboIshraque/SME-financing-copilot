import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";

import { apiGet, type Health } from "../api/client";

/** Shown whenever the server runs on synthetic data (CLAUDE.md rule 8). */
export function DemoBanner() {
  const { t } = useTranslation();
  const { data } = useQuery({ queryKey: ["health"], queryFn: () => apiGet<Health>("/api/health") });
  if (data?.data_mode_banner !== "synthetic") return null;
  return (
    <div role="status" className="bg-amber-100 px-4 py-2 text-center text-sm text-amber-900">
      {t("banner.synthetic")}
    </div>
  );
}
