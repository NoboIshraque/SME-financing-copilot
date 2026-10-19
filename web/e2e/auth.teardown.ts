// Runs last on each target (project "<target>-teardown"): signs every saved session out, so the
// session cookies that traces recorded open nothing afterwards, and removes the files.
import { existsSync, rmSync } from "node:fs";

import { expect, test as teardown } from "@playwright/test";

import { SAVED_ROLES, sessionFile } from "./support/auth";
import { apiContext } from "./support/target";

teardown("sign the saved sessions out", async () => {
  for (const file of [...SAVED_ROLES, "critical_owner" as const].map(sessionFile)) {
    if (!existsSync(file)) continue;
    const api = await apiContext(file);
    const check = await apiContext(file); // keeps the old cookie: the server must refuse it now
    try {
      await api.post("/api/auth/logout");
      expect((await check.get("/api/auth/me")).status(), file).toBe(401);
    } finally {
      await api.dispose();
      await check.dispose();
      rmSync(file, { force: true });
    }
  }
});
