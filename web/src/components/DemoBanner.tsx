import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";

import { api } from "../api/endpoints";
import { useMockInUse } from "../api/mockUsage";
import { useSession } from "../auth/session";

/** Shown whenever the server runs on synthetic data (CLAUDE.md rule 8), and whenever any answer
 *  on the page came from the offline mock instead of the real engines. */
export function DemoBanner() {
  const { t } = useTranslation();
  const { data } = useQuery({ queryKey: ["health"], queryFn: api.health, staleTime: 10 * 60_000 });
  const mocked = useMockInUse();
  const session = useSession();
  // Signed in, the banner follows the shop: a self-service shop's data is its owner's own.
  const synthetic = session.data ? session.data.data_mode === "synthetic" : data?.data_mode_banner === "synthetic";
  if (!synthetic && !mocked) return null;
  return (
    <div role="status" className="bg-amber-100 px-4 py-2 text-center text-sm text-amber-900 dark:bg-amber-900 dark:text-amber-50">
      {synthetic && <span>{t("banner.synthetic")}</span>}
      {mocked && <span className="block font-medium">{t("banner.mock")}</span>}
    </div>
  );
}
