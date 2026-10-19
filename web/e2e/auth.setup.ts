// Runs first on each target (project "<target>-setup"): signs the demo roles in once and saves
// their sessions for every journey (support/auth.ts). Journeys that test signing in themselves
// start signed out.
import { rmSync } from "node:fs";

import { test as setup } from "@playwright/test";

import { demoAccounts, HOME_TENANT_INDEX } from "./support/accounts";
import { saveSession, SAVED_ROLES, sessionFile, signInThroughApi } from "./support/auth";
import { apiContext, routeIsLive } from "./support/target";

for (const role of SAVED_ROLES) {
  setup(`sign in the demo ${role}`, async () => {
    const api = await apiContext(); // one cookie jar per role
    try {
      await saveSession(api, role);
    } finally {
      await api.dispose();
    }
  });
}

interface AlertView {
  tier: string;
  fixes?: { tier: string }[] | null;
}

// The Critical-alert journey needs a business the cash engine (WP-04) really flags as Critical
// today. Which one that is follows from the ledger, so ask the engine, owner by owner (the home
// business last: the journeys above are signing its owner in at the same time).
setup("sign in the owner of a business with a Critical cash alert", async () => {
  const file = sessionFile("critical_owner");
  rmSync(file, { force: true });
  setup.skip(!(await routeIsLive("GET /api/cash/alerts")), "WP-04's cash router is not live: the journey uses a stand-in");
  setup.setTimeout(300_000);

  const lookup = await apiContext();
  const accounts = await demoAccounts(lookup);
  await lookup.dispose();
  const home = accounts[HOME_TENANT_INDEX]?.business_name;
  const owners = accounts.filter((account) => account.role === "owner");
  const ordered = [...owners.filter((owner) => owner.business_name !== home), ...owners.filter((owner) => owner.business_name === home)];

  for (const owner of ordered) {
    const api = await apiContext();
    try {
      await signInThroughApi(api, owner);
      const response = await api.get("/api/cash/alerts");
      const alerts = response.ok() ? ((await response.json()) as AlertView[]) : [];
      if (alerts.some((alert) => alert.tier === "critical" && (alert.fixes ?? []).some((fix) => fix.tier === "EXECUTE"))) {
        await api.storageState({ path: file });
        setup.info().annotations.push({ type: "critical owner", description: owner.business_name });
        return;
      }
      await api.post("/api/auth/logout");
    } finally {
      await api.dispose();
    }
  }
  setup.info().annotations.push({ type: "critical owner", description: "none: no demo business has a Critical alert" });
});
