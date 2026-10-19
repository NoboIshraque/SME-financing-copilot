// Flow 5: the liquidity mesh (WP-08 through WP-14's Mesh screen): the debt ring, the proposed
// netting round, an owner's approval with a step-up code, and the testnet anchor of a settled
// round checked against the chain.
//
// Until WP-08's API lands, the offline mock answers, and it can only play one business: it acts
// as the ring member its routes default to (web/src/mocks/routes/mesh.ts) and keeps approvals in
// one page's memory, so "every party approves" across three owners' sessions waits for the real
// router (WP-15.md, Notes). This journey signs in as that member and approves for it.
import { readFileSync } from "node:fs";
import { join } from "node:path";

import { demoAccounts } from "../support/accounts";
import { expect, test, type StepUpCall } from "../support/fixtures";
import { tPattern } from "../support/i18n";
import { needsRoutes, routeIsLive, WEB_DIR } from "../support/target";

const MESH_APPROVE: StepUpCall = { route: "POST /api/mesh/rounds/probe/approve", url: /\/api\/mesh\/rounds\/[^/]+\/approve$/ };

/** The business the mock's mesh routes answer as, read from the mock itself. */
function mockRingMember(): string {
  const routes = readFileSync(join(WEB_DIR, "src", "mocks", "routes", "mesh.ts"), "utf8");
  const fixtures = readFileSync(join(WEB_DIR, "src", "mocks", "fixtures", "mesh.ts"), "utf8");
  const tenant = /tenant_id \?\? "(\w+)"/.exec(routes)?.[1];
  const label = tenant ? new RegExp(`${tenant}: "([^"]+)"`).exec(fixtures)?.[1] : undefined;
  if (!label) throw new Error("the mock's default mesh member was not found");
  return label;
}

test.use({ storageState: { cookies: [], origins: [] } });

test("a ring member's owner approves the proposed netting round with a code, and a settled round's testnet anchor verifies", async ({ app, page }) => {
  test.skip(await routeIsLive("GET /api/mesh/rounds"), "WP-08's mesh API is live: this mock-backed journey gives way to the multi-party one");
  await needsRoutes(["GET /api/mesh/rounds", "POST /api/mesh/rounds/probe/approve"]);
  const member = mockRingMember();
  const owner = (await demoAccounts(page.request)).find((account) => account.role === "owner" && account.business_name === member);
  if (!owner) throw new Error(`no demo owner for ${member}`);
  await app.signInAs(owner);

  await app.start("mesh");
  const graph = page.getByRole("region", { name: app.t("mesh.graphTitle") });
  await expect(graph.getByRole("listitem").filter({ hasText: member })).not.toHaveCount(0);

  const rounds = page.getByRole("region", { name: app.t("mesh.roundsTitle") });
  const proposed = rounds.getByRole("article").filter({ hasText: app.t("mesh.proposedTitle") });
  const myApproval = proposed.getByRole("listitem").filter({ hasText: `${member} (${app.t("mesh.you")})` });
  await expect(myApproval).toContainText(app.t("mesh.waiting"));
  // Gross debt cleared, and the far smaller cash that actually moves.
  await expect(proposed).toContainText(app.t("mesh.clears"));
  await expect(proposed).toContainText(app.t("mesh.withCash"));

  await proposed.getByRole("button", { name: app.t("mesh.approve") }).click();
  await expect(app.stepUpDialog().getByText(tPattern("mesh.stepUpSummary", { gross: ".+", net: ".+" }))).toBeVisible();
  await app.confirmStepUp(owner, MESH_APPROVE);
  await expect(myApproval).toContainText(app.t("mesh.approved"));
  await expect(proposed.getByText(tPattern("mesh.waitingFor", { names: ".+" }))).toBeVisible();

  // A settled round: only a salted hash is on the testnet, and anyone can check it.
  const settled = rounds.getByRole("article").filter({ hasText: app.t("mesh.chain.sepolia") });
  await expect(settled.getByText(tPattern("mesh.tx", { hash: "0x[0-9a-f]{64}" }))).toBeVisible();
  await expect(settled).toContainText(app.t("mesh.hashOnly"));
  await settled.getByRole("button", { name: app.t("mesh.verify") }).click();
  await expect(settled.getByRole("status")).toHaveText(app.t("mesh.valid"));
});
