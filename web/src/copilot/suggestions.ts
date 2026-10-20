// Suggested questions per role, as i18n keys. Each one is a question the copilot answers from
// the role's own data (backend/tests/agents/test_suggestions.py plans every one of them), so a
// suggestion can never come back as "I won't guess". Compliance and lender viewers cannot ask
// the copilot (the API refuses copilot:ask), so they get none and the panel is not shown.
import type { Role } from "../api/contracts";

export const SUGGESTIONS: Record<Role, readonly string[]> = {
  owner: ["copilot.suggest.owner.1", "copilot.suggest.owner.2", "copilot.suggest.owner.3", "copilot.suggest.owner.4"],
  accountant: ["copilot.suggest.accountant.1", "copilot.suggest.accountant.2", "copilot.suggest.accountant.3"],
  staff: ["copilot.suggest.staff.1", "copilot.suggest.staff.2", "copilot.suggest.staff.3"],
  compliance: [],
  lender_viewer: [],
};

/** Roles that may upload a statement from the panel get that as a suggestion too. */
export const UPLOAD_SUGGESTION: Record<Role, boolean> = {
  owner: false, // owners have the upload button right above; four questions are enough
  accountant: true,
  staff: false,
  compliance: false,
  lender_viewer: false,
};

export const HELP_TOPICS = ["cash", "payments", "owed", "loans", "health", "whatif", "debts"] as const;

export function suggestionsFor(role: Role): readonly string[] {
  return SUGGESTIONS[role] ?? [];
}
