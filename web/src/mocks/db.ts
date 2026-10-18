// In-memory state of the offline mock API. Every value is synthetic (CLAUDE.md rule 8).
import type { Approval, NettingRound, Role } from "../api/contracts";
import type { Session } from "../api/types";
import { initialRounds } from "./fixtures/mesh";

export const DEMO_PASSWORD = "hishab-demo";
export const DEMO_TOTP_CODE = "246810";
export const MAX_FAILED_LOGINS = 5;

export interface MockUser {
  email: string;
  password: string;
  role: Role;
  display_name: string;
  tenant_id: string;
  business_name: string;
  totp: boolean;
  scopes: string[];
  expires_at: string | null;
  failedLogins: number;
}

export interface MockDb {
  users: MockUser[];
  session: Session | null;
  /** Email of a user who passed the password step and still owes a TOTP code. */
  pendingTotp: string | null;
  approvals: Approval[];
  /** Invoice id -> dispute reason, for invoices disputed in this session. */
  disputes: Record<string, string>;
  rounds: NettingRound[];
}

/** The caller's role. In "auto" mode the real backend may own the session while the mock still
 *  answers a route, so an unknown session is treated as the owner. */
export function callerRole(db: MockDb): Role {
  return db.session?.principal.role ?? "owner";
}

function user(email: string, role: Role, displayName: string, totp: boolean, extra: Partial<MockUser> = {}): MockUser {
  return {
    email,
    password: DEMO_PASSWORD,
    role,
    display_name: displayName,
    tenant_id: "sme_grocery",
    business_name: "Mirpur Mudi Store",
    totp,
    scopes: [],
    expires_at: null,
    failedLogins: 0,
    ...extra,
  };
}

export function demoUsers(): MockUser[] {
  return [
    user("owner@hishab.demo", "owner", "Demo owner", true),
    user("accountant@hishab.demo", "accountant", "Demo accountant", false),
    user("staff@hishab.demo", "staff", "Demo staff", false),
    user("lender@hishab.demo", "lender_viewer", "Lender 1 (demo)", false, {
      scopes: ["passport:read"],
      expires_at: "2026-10-25T18:00:00Z",
    }),
    user("compliance@hishab.demo", "compliance", "Demo compliance officer", false),
    user("garment@hishab.demo", "owner", "Demo garment owner", true, {
      tenant_id: "sme_garment",
      business_name: "Ashulia Stitch Works",
    }),
  ];
}

export function sessionFor(account: MockUser): Session {
  return {
    principal: {
      user_id: `u-${account.email.split("@")[0]}`,
      tenant_id: account.tenant_id,
      role: account.role,
      scopes: account.scopes,
      expires_at: account.expires_at,
    },
    display_name: account.display_name,
    business_name: account.business_name,
    totp_enrolled: account.totp,
    data_mode: "synthetic",
  };
}

/** Fresh mock state. `signedInAs` starts a session for that demo email (tests skip the login). */
export function createMockDb(options: { signedInAs?: string } = {}): MockDb {
  const users = demoUsers();
  const db: MockDb = { users, session: null, pendingTotp: null, approvals: [], disputes: {}, rounds: initialRounds() };
  if (options.signedInAs) {
    const account = users.find((u) => u.email === options.signedInAs);
    if (!account) throw new Error(`no demo user ${options.signedInAs}`);
    db.session = sessionFor(account);
  }
  return db;
}
