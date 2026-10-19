// Runs first on each target (project "<target>-setup"): signs the demo roles in once and saves
// their sessions for every journey (support/auth.ts). Journeys that test signing in themselves
// start signed out.
import { test as setup } from "@playwright/test";

import { saveSession, SAVED_ROLES } from "./support/auth";
import { apiContext } from "./support/target";

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
