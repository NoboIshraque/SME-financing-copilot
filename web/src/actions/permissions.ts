// What the signed-in role may do with an action card. A calm-UI convenience: the API checks the
// same rules (WP-11 policy table) and has the final word.
import type { Role, Tier } from "../api/contracts";

export type Ability = "approve" | "request" | "open" | "owner_only" | "role_cannot" | "never";

export function abilityFor(tier: Tier, role: Role): Ability {
  switch (tier) {
    case "READ":
      return "open";
    case "DENY":
      return "never";
    case "EXECUTE":
      if (role === "owner") return "approve";
      return role === "accountant" ? "request" : "owner_only";
    case "DRAFT":
      return role === "owner" || role === "accountant" ? "approve" : "role_cannot";
    case "SUGGEST":
      return role === "owner" || role === "accountant" || role === "staff" ? "approve" : "role_cannot";
  }
}
