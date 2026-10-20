# Session B, added task B5: bring the Market feature back (WP-09)

Nobo decided on 20 Oct to re-include Market watch, vendor ranking and negotiation (N3, N19),
which were cut on 19 Oct. This file extends `docs/handover/SESSION_B_APP.md`; its rules,
branch habits and ownership still apply, plus the paths below.

## Order and time box

1. Finish **B1** (first owner sign-in) and merge it.
2. Then **B5** (this file). Hard stop for new B5 work at **18:30 Dhaka**: merge whatever is
   complete and green, and leave the rest of the screen on its labelled sample data.
3. Then **B2** (slider) if time remains. **B3** changes: keep the "sample data" label only on the
   parts B5 did not make live.

## You now also own

`backend/app/engines/market/`, `backend/app/api/market.py`, `backend/tests/market/`,
`data/public/prices/`, `web/src/screens/market/`, `docs/packages/WP-09.md`, `docs/FEATURES.md`
rows N3/N19, and in `docs/submission/` only the lines that say Market was cut (technical
documentation status table and limits, the deck's `limits.html`, the video script). Do **not**
touch `backend/app/agents/` or `backend/app/llm/` (Session A): when your API is merged, tell
Nobo so Session A can register the market tools for the copilot.

## What already exists

- The web screen `web/src/screens/market/` and the API calls in `web/src/api/endpoints.ts`
  (`market.prices`, `market.alerts`, `market.vendors`, `market.negotiate`). Each uses
  `orSample(...)`: it calls the server and falls back to the bundled sample in
  `web/src/mocks/fixtures/market.ts` **only when the route does not exist**. Build the routes and
  the screen goes live without changing those calls.
- The shapes the web expects are in `web/src/api/types.ts`: `WatchItem`, `MarketAlert`,
  `VendorRank`, `NegotiationRequest`, `NegotiationPlan` (and `PricePoint`, `VendorQuote`). Match
  them exactly; check `web/src/api/contracts.ts` for `Figure` and `Money`, and reuse contracts
  from `backend/app/contracts` (do not change a contract; if one is missing, write a router-local
  Pydantic model with the same JSON shape).
- Spec: `docs/packages/WP-09.md` (milestones 1–5). Nothing in `backend/` exists yet.

## Rules that matter most here (CLAUDE.md)

- **No invented prices.** Every price comes from a real public source with its name, URL and
  publication date, or the route abstains (422 with what is missing). Never let a model produce
  a price. Never make up "real" vendors.
- Engines are pure functions over contracts, `Decimal` money, every figure with provenance
  (`formula_id` + inputs), tests offline (save fetched pages as fixtures).
- Synthetic stays labelled synthetic: vendor quotes for the five demo shops may be generated, but
  `data_mode: "synthetic"` and named "Supplier 1/2/3" style labels.

## Build, smallest useful first

1. **Prices (milestone 1 + `GET /api/market/prices`).** Get a real snapshot of Dhaka retail
   prices for 8–12 common inputs (rice, lentils, soybean oil, sugar, flour, onion, potato, egg…):
   first choice the TCB daily price list (tcb.gov.bd, published daily, Bangla/English), second
   choice WFP Bangladesh market prices on HDX (CC BY). Fetch from your session; if neither host is
   reachable, ask Nobo once to allow it in the environment's network settings. Save the raw page
   under `data/public/prices/<source>/<date>.*` with a `README.md` (source, URL, licence, date),
   parse to price points, and serve `WatchItem[]` (latest, 4-week median when you have ≥ 4
   snapshots, else say so; change %, history). Show the publication date on screen ("published
   on …"), never "live".
2. **Alerts (`GET /api/market/alerts`).** Move past ±5% against the 4-week median (or against
   the previous snapshot when fewer than 4 exist, stated in the figure's provenance).
3. **Negotiation (`POST /api/market/negotiate`, N19).** Pure math: walk-away price = the price
   at which buying on `payment_days` credit costs the same as paying cash today at the shop's
   cost of money (best eligible APR from the financing engine, `backend/app/engines/financing`),
   target a stated share inside it, and 3–4 script steps (`text_key` in en/bn/zh) each with its
   figures. Property test: never recommends terms worse than walk-away.
4. **Vendors (`POST /api/market/vendors/rank`).** Landed cost = quoted price × quantity +
   delivery + expected delay cost (late days × daily cost of money) + reliability penalty from
   the shop's own history (on-time share of that supplier's bills in the fact store). Quotes:
   for the demo shops, generated synthetic quotes from their real ledger suppliers; for a
   self-service shop, abstain with "add a supplier quote" unless you also have time for a small
   quote form. Stable ranking under irrelevant noise (test).
5. **Docs:** WP-09.md STATUS, FEATURES.md N3/N19 back to IN (with what is live and what is not),
   PLAN §8 WP-09 row, the submission docs' "Market cut" lines; regenerate `npm run evidence` and
   the PDFs (`uv run --no-project --with markdown python scripts/export_submission_pdfs.py`;
   the deck needs Space Grotesk, IBM Plex Sans and Noto Sans Bengali installed) and check the
   deck pages visually.

Each step is its own PR, merged when CI (including "Playwright (local target)") is green. Add
`tests/market/` cases for each piece and one e2e check that the Market screen shows the live
source and date instead of the sample label.
