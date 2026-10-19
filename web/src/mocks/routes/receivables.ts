// Mock of the WP-05 receivables router: aging, risk, reminder ladder, dispute log.
import { receivableRows, receivablesOverview, reminderPlan } from "../fixtures/receivables";
import { apiError, field, ok, type MockRoute } from "../http";

export const receivablesRoutes: MockRoute[] = [
  { method: "GET", pattern: "/api/receivables", handler: (_req, db) => ok(receivablesOverview(db.disputes)) },
  { method: "GET", pattern: "/api/receivables/plan", handler: () => ok({ reminders: reminderPlan() }) },
  {
    method: "POST",
    pattern: "/api/receivables/:id/dispute",
    handler: (req, db) => {
      const id = req.params.id ?? "";
      if (!receivableRows(db.disputes).some((row) => row.invoice.id === id)) return apiError(404, "not_found", "error.not_found");
      const reason = field(req.body, "reason").trim();
      if (!reason) return apiError(422, "reason_required", "error.reason_required");
      db.disputes[id] = reason;
      return ok(receivableRows(db.disputes).find((row) => row.invoice.id === id));
    },
  },
  {
    method: "POST",
    pattern: "/api/receivables/:id/resolve",
    handler: (req, db) => {
      const id = req.params.id ?? "";
      if (db.disputes[id] === undefined) return apiError(409, "not_disputed", "error.not_disputed");
      delete db.disputes[id];
      return ok(receivableRows(db.disputes).find((row) => row.invoice.id === id));
    },
  },
];
