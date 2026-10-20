# Feature list — SME Finance Copilot (working name: DecisionGuard)

> **Scope cuts approved by Nobo, 19 Oct 22:19 Dhaka**, to fit the time before the 20 Oct deadline. Kept whole:
> WP-10 agents (done). Cut: WP-09 market (N3, N19; **re-included 20 Oct by Nobo, reduced**), WP-12 sending channels (N2 keeps drafts in
> the approval queue), P8 audit drill, WP-17 GPU injection run and market backtest, WP-18 Vercel
> mirror, WP-13 lender report (Tuesday only if time allows). Shortened: WP-05 to milestones 1, 2,
> 4, 7; WP-15 to about 12 flows; WP-16 to about 40 tasks without mutation score. P7 real shop
> data is substituted by public real datasets (WP-20.md). Every idea stays in this file as roadmap.

FinTechathon 2026 · International Track · Topic E · Team: Nobo, Amdad, Labib

Topic E brief (official): *a finance copilot for small-business owners, offering
financing-option matching, cash-flow management with alerts, and business financial
analysis.* Theme: *AI as a Financial Participant* — the agent must complete real tasks.

## Legend

| Tag | Meaning |
| --- | --- |
| **N1–N20** | Nobo's own feature points (all are IN; none dropped) |
| **Q1–Q4** | Nobo's open questions, answered as features (IN) |
| **P1–P14** | Proposed additions from Claude — **decided by Nobo on 17 Oct: all IN except P10 (CUT)**. Never build a CUT item |
| Status | `IN` = approved and in scope · `PENDING` = awaiting approval · `CUT` = rejected |

Four groups: the three official Topic E categories (A, B, C), plus **D — Engine room**, for
Nobo's cross-cutting points that power all three (typed facts, agents, checker, privacy…).
Every feature lives in exactly one group; the cross-check table at the end proves it.

---

## A. Financing-option matching

| ID | Feature | Status | How it works |
| --- | --- | --- | --- |
| **N14** | **Liquidity mesh** — a network linking SMEs, buyers, suppliers and lenders. Settles netting rounds; each settled round's hash is recorded on a public testnet | IN | Mesh graph of obligations (who owes whom, when). Detects cycles of mutual debt (A→B→C→A) and computes a **multilateral netting round** (min-cost-flow), so circular baki clears with little real cash. Every party approves; settlement record is hashed and anchored on Ethereum Sepolia (testnet, no real money, **hashes only, never personal data**). After netting, any remaining gap is routed to the cheapest path (buyer early pay, supplier terms, or a lender). Doubles as the on-chain challenge bonus (0–5 pts) |
| **N20** | **Online/digital lender check from track record** (via the mesh) | IN | Lender profile = realised vs quoted cost, approval speed, hidden fees, complaint/dispute rate, repayment-terms fairness, licence status. Built from mesh events (each SME's actual borrowing experience) + published data. Cold start: seed from public sources (licence lists, published rates) + clearly labelled synthetic mesh history |
| **Q4** | **State data platform answer → "Trust Passport"** | IN | See answer Q4 below. A consented, counterparty-attested, hash-anchored evidence pack the SME carries to any lender |
| P1 | **Cost-transparent financing ranking** — all options (loans *and* non-loan: buyer early pay, supplier term extension, factoring, netting, grants) ranked by **effective annual cost**, eligibility with "why you qualify / don't", repayment fit against the forecast, approval likelihood. Real Bangladesh products with source links and published rates | IN (**MUST**) | Without P1, group A has the mesh and lender check but no actual "matching". Rivals do this; we must too, and better (they use simulated products) |
| P14 | China jurisdiction pack — a second product catalogue modelled on WeBank-/MYbank-style digital SME credit, to show the engine is portable | IN (nice) | Same engine, second catalogue file. Judges are WeBank |

## B. Cash-flow management with alerts

| ID | Feature | Status | How it works |
| --- | --- | --- | --- |
| **N2** | **Systemised/automated ledger-based messages** to buyers, lenders and sellers, to cut workload | PARTIAL (19 Oct: drafts in the approval queue; sending cut) | Ledger events trigger drafts: pre-due reminders to buyers, payment-plan offers, supplier term-extension requests, lender status updates. Templates in English and Bangla. Tiered approval: low-risk reminders can auto-send once the owner opts in; anything with money or commitments needs owner approval |
| **N3** | **Market watch** — price drops for raw materials/inputs notified; also recommends which vendor and route to use | IN, reduced (re-included 20 Oct). **Live:** 13 inputs from TCB's published daily Dhaka retail lists (10 lists, 10-19 Oct, saved in the repo), 4-week median, alerts past ±5% with /explain, vendor ranking by landed cost for the demo shops' own ledger suppliers. **Not live:** AgriPriceBD and Pink Sheet, scheduled fetching, real vendor quotes (generated, synthetic), quote form for self-service shops, pickup vs delivery route | Daily ingest of public prices (TCB Dhaka daily market prices; AgriPriceBD daily agri prices; World Bank monthly commodity "Pink Sheet") + the SME's own vendor quotes from its ledger. Alert when a tracked input drops/rises past a threshold; vendor ranking by landed cost (price + delivery cost + delay + reliability). *Honest limit: public data is daily/monthly, not tick-by-tick, so "immediately" = same day it is published* |
| **N19** | **Negotiation support when choosing a buyer**, with instruction breakdowns | IN, reduced (re-included 20 Oct). **Live:** walk-away at the best eligible APR (WP-06), target, 3-4 step script with its figures; property-tested never below walk-away. **Not live:** advance and volume trade-offs | For each buyer/deal: computes our walk-away point, target terms and the trade-offs (price vs payment term vs advance vs volume), e.g. "offer 2% off for payment in 7 days — that costs 0.7% a month, cheaper than the 1.4%/month loan". Outputs a step-by-step script and the numbers behind each step |
| **Q1** | **Uneven cash flow → smoothing + alert system** | IN | See answer Q1 below |
| **Q2** | **Unpaid receivables → causes tackled one by one** | IN | See answer Q2 below |
| **Q3** | **Spot cash gaps before they happen** | IN | See answer Q3 below |
| P10 | Telegram bot channel + WhatsApp click-to-chat drafts (owner taps, WhatsApp opens with the message pre-filled) | **CUT** (Nobo, 17 Oct) | Bangladeshi owners live in messaging apps; Telegram bots are free; WhatsApp deep links need no API |

## C. Business financial analysis

| ID | Feature | Status | How it works |
| --- | --- | --- | --- |
| **N1** | **Weekly / quarterly expected-vs-reality check**, decisions based on it | IN | Every forecast is frozen as a snapshot. Each week/quarter the engine compares snapshot vs actuals line by line (sales, collections, costs, balance), explains the biggest variances, scores forecast accuracy, and feeds corrections back into the next forecast and into recommendations |
| **N4** | **Quarterly / year-end automated lender report**, linked to simulated future scenarios showing how the SME will generate profit | IN | PDF + web report: cash-basis P&L, balance-sheet-lite, ratios, trends, receivables quality, forecast with bands, scenario outcomes (from N12), provenance appendix. Hash-anchored so a lender can verify it wasn't edited. Feeds the Trust Passport (Q4) |
| **N12** | **Multi-variable simulations** of different cases, future impacts, suggest the right path (works with N4) | IN | Monte Carlo over sales, collection delays, input prices, interest rates, one-off shocks. Compares candidate decisions (take loan A / loan B / net via mesh / offer discount / delay purchase) by expected outcome, worst-5% outcome and probability of breaching the cash buffer. Recommends the path with the best risk-adjusted result |
| **N16** | **Decision stability score** — each decision re-run under ~10 variations: economic stress *and* irrelevant noise | IN | Economic stress (late payer, −10/−20% sales, +8% input prices, +2pp rates, surprise bill): advice *may* change — we show where it breaks ("only works if Karim pays on time"). Irrelevant noise (reordered rows, reworded question, renamed parties): advice *must not* change — any flip is flagged as unreliable. Score shown as a bar beside each recommendation |
| P9 | **"Rails, not chat"** — each recommendation becomes 1–3 pre-checked action cards with one-tap approve (draft loan application, send reminder, propose netting) | IN (strong) | Kenya RCT: open chat helped strong owners and *hurt* weak ones (−8%). Action cards fix that, and they show "AI completes tasks" (40% of score) |

## D. Engine room (powers A, B and C)

| ID | Feature | Status | How it works |
| --- | --- | --- | --- |
| **N5** | **Typed facts** — every calculation uses structured records with labelled fields, never loose text | IN | Typed Fact Ledger: `{metric, value, currency, period, party_token, source_ref, …}`. Lookups are exact (`net_sales` for `2026-Q2`), never similarity search. No Net Income/Net Sales mix-ups |
| **N6** | **Anonymised inputs** to any AI model | IN | Implemented by N18. Also blocks memorisation leaks (see N15) |
| **N7** | **Code does the maths** — LLM writes/selects code, code runs, results and recommendations come from the code's output | IN | Deterministic engines (Decimal arithmetic) do every number. The LLM chooses tools and explains results; it never produces a number that isn't from a tool. Research: Program-of-Thoughts ≈ +12% over chain-of-thought; VeNRA ledger + Python ≈ 1.2% hallucination |
| **N8** | **Multi-agent system** — main agent, sub-agents for parallel tasks, a **specialised checker** that verifies claims against structured data with a symbolic solver | IN | Orchestrator → sub-agents (cash, receivables, financing, analysis, market, messaging). Every claim is emitted as `{claim, value, formula_id, inputs[]}`; the checker recomputes it from the fact ledger (SymPy / exact recomputation) and rejects any mismatch (VeriFin-style acceptance control) |
| **N9** | **Multi-model agreement beats self-stated confidence** — several models run the same thing | IN | Different model families (Gemini + gpt-oss + Qwen) run the same judgement; agreement rate is the confidence. Applies to judgement calls (which option, which intent, extraction) — numbers always come from code. Run only above a stakes threshold, to respect free-tier quotas |
| **N10** | **Self-loops through sub-agents** — rerun with stressed inputs and many test cases, push each recommendation to its limits | IN | Before a recommendation is shown: stress loop (N16 variations) + checker (N8) + critic (N11). Stakes-tiered so cheap actions don't burn quota; results cached |
| **N11** | **Dedicated flaw-finder agent** working alongside the checker | IN | "Case against" critic from a *different* model family, required to argue the opposite of every material recommendation. Its strongest objection is shown to the owner. (Research: LLMs can't self-correct reliably without external feedback — Huang et al., ICLR 2024 — so the critic is a separate model + data, not self-reflection) |
| **N13** | **Every number is clickable** — opens the formula and the source transactions | IN | Provenance graph: each displayed figure carries `formula_id` + input fact IDs → source rows. Click → drawer with formula, inputs, and the original transactions (masked per role) |
| **N15** | **Forecasts evaluated only on data the model can't have seen** | IN | Walk-forward backtests on post-cutoff periods; anonymised entities/dates for any LLM step (Lopez-Lira et al.: LLMs recall pre-cutoff data; post-cutoff accuracy dropped to 40%). Statistical forecaster backtested on real public data, never on data we generated |
| **N17** | **Required "I don't know"** — agreement check, data-sufficiency check, stakes-based thresholds, specific asks, every abstention logged | IN | Abstain when: models disagree beyond tolerance; history too short (e.g. < 8 weeks for a weekly forecast); checker can't verify. Thresholds rise with stakes (reminder < borrowing < moving money = always human). Abstention message names exactly what's missing ("upload last quarter's supplier bills"). Abstention log feeds the trust report |
| **N18** | **Privacy by anonymisation** — names, IDs, numbers replaced by tokens | IN | Local detector (BD phone, NID, bKash/bank numbers, names, addresses) → tokens (`CUSTOMER_7`); originals in an AES-256-GCM vault on our server; only tokens reach any external model; restored only for authorised roles |
| P2 | **Security & permission tiers** — roles (owner, accountant, staff, lender-viewer); tiers READ / SUGGEST / DRAFT / EXECUTE / DENY; owner approval with step-up code for EXECUTE; hash-chained audit log anchored on testnet; rate limits, CSP, secret scanning | IN (**MUST**) | Deliverable 05 literally requires "permission-tier implementation and known-risk list". Security = 30% of score |
| P3 | **Evaluation harness + execution evidence** — scripted functional tasks + adversarial suite, run in CI, logs exported | IN (**MUST**) | Deliverable 06 requires sandbox operation logs; "task completion" (40%) needs proof |
| P4 | **Mobile-money-first ingestion** — bKash/Nagad statements, bank CSV/Excel, ledger photos (OCR), Bangla/Banglish text | IN (strong) | Rivals all assume formal SMEs. This is our home-turf edge |
| P5 | **Multilingual prompt-injection guard** (Bangla, Banglish, Chinese, English) with a trained classifier and a *measured* catch rate on paraphrased attacks | IN (strong) | Both leading rivals admit their pattern-based guards are untested on paraphrases |
| P6 | **China-reachable hosting + Chinese UI** (EN/BN/ZH) | IN (strong) | Judges are in Shenzhen; DuitDuit needs a VPN |
| P7 | **Real data from 3–5 consenting Dhaka shops** (anonymised) + interview quotes | SUBSTITUTED (19 Oct: public real datasets; field data only if it arrives) | Every rival is 100% synthetic |
| P8 | **Nightly audit drill** — plant errors in a sandbox copy of the ledger; publish the copilot's catch rate as a trust score | CUT (19 Oct) | Turns "trust us" into a number |
| P11 | Amount scaling — multiply amounts by a secret factor before any LLM sees them (ratios survive, scale hidden) | IN (nice) | Extension of N18; thresholds stay in code |
| P12 | Accessibility (WCAG 2.1 AA) + installable mobile PWA | IN (nice) | DuitDuit reports 0 axe violations; cheap parity |
| P13 | Agent "tool budget" per run (max tool calls, max cost) | IN (nice) | Stops runaway loops; security story |

---

## Answers to the open questions (Q1–Q4)

### Q1 — Uneven cash flow + a cash-flow alert system

**Why it happens (the causes we design against):** seasonality (Eid, Pohela Boishakh,
harvests), lumpy B2B collections, obligations bunched at month start (rent, salaries,
loan EMIs), bulk stock purchases, one-off shocks (repairs, fines), and buyers paying late.

**Fix 1 — see it:** a daily balance forecast for 13 weeks with best/likely/worst bands (Q3).

**Fix 2 — smooth it (the copilot proposes, owner approves):**
- Re-time outflows *within* existing terms (pay the supplier on day 29, not day 3).
- Stagger bulk purchases; split one big buy into two when the price trend allows (N3).
- Ask for partial advances or milestone billing on large orders (N19 negotiation).
- Offer early-pay discounts only when cheaper than borrowing (A/P1 ranking).
- Net circular debts through the mesh (N14).
- Keep a **cash buffer target** = the amount that covers the worst-case dip in 19 of 20
  simulated paths; sweep surplus weeks into it.
- Line up a standby facility *before* the gap (best-ranked option from group A).

**Fix 3 — alert on it (tiers):**

| Tier | Trigger | Delivery |
| --- | --- | --- |
| Watch | Probability of dipping below buffer > 20% within 22–90 days | In-app, weekly digest |
| Warning | > 20% within 8–21 days, or > 50% within 22–45 days | In-app + email |
| Critical | > 20% within 7 days, or > 60% within 21 days, or a missed payroll/EMI projected | In-app + email, pinned to the top of the Today screen |

Every alert says: **what, when, how much, why** (which customer/bill causes it), and
**ranked fixes with their cost**, each as a one-tap action card. Alert fatigue control:
no duplicate alert unless the forecast moves materially (> 10% or > 3 days); cooldown per alert.

### Q2 — Why unpaid receivables happen, and how we tackle each cause

| Cause | Evidence | Our counter |
| --- | --- | --- |
| Informal credit culture (baki as loyalty), no written terms | Bangladesh CMSME bookkeeping gaps (Daily Star) | Digital memo at the moment of sale with amount and due date, sent to the buyer (N2) |
| Forgetfulness | Many late payments are forgetfulness; QuickBooks: AI reminders → paid ~5 days faster | Polite **pre-due** reminders in Bangla/English, then a gentle escalation ladder |
| Power imbalance with big buyers | UK: 50% say they have little control over big corporates; China: 71% of small firms carry arrears | Negotiation scripts (N19), factoring/early-pay options (group A), late-fee terms on new deals |
| Buyer's own cash crunch (arrears ripple down chains) | Peking University survey | Payment-plan offers; **mesh netting** (N14) clears circular debt |
| Disputes (quality/quantity) | — | Dispute log on each invoice; a disputed invoice is excluded from the "likely" forecast until resolved |
| No cost to paying late; awkward to chase | QuickBooks: ~14 h/week on collections | Automated, owner-approved chasing; per-customer **credit limit** from payment history; "stop credit" suggestion for chronic late payers |
| Hard to pay | — | Payment link/QR (bKash) in every reminder |

Per-customer **risk score** (payment-delay model trained on Kaggle) drives credit limits,
reminder timing and which invoices are counted as "likely" in the forecast.

### Q3 — Spot cash gaps *before* they happen

1. **Model:** balance(day) = opening balance + expected inflows − expected outflows.
   - Inflows: open invoices × each customer's learned payment-delay distribution;
     recurring sales with day-of-week, month-end and festival seasonality.
   - Outflows: known schedule (rent, salaries, EMIs, supplier due dates) + recurring costs.
2. **Simulate:** 1,000 Monte Carlo paths → for each day, probability balance < buffer;
   first crossing date; expected shortfall (Tk); lead time.
3. **Leading indicators** that fire even before the forecast crosses: DSO rising, a top
   customer's payments slowing, stock building faster than sales, sales below the seasonal norm.
4. **Prove it works:** walk-forward backtest on real data (N15): "how many days ahead did
   we flag the gaps that actually happened?" — reported as lead time and hit rate.
5. **Act:** alert tier (Q1) + ranked fixes as action cards.

### Q4 — The state data platform problem

China solved lender blindness with a **state** platform (74 data items, RMB 37.3T lent through
it). Bangladesh has no equivalent, and we can't build one. So we build it **bottom-up, owned
by the SME**:

- **Trust Passport** = the SME's own verifiable evidence: bKash/Nagad and bank statements,
  trade licence, e-TIN/BIN registration, utility bills, the N4 reports.
- **Counterparty attestations via the mesh:** when buyer and seller both confirm the same
  invoice/payment, that record is far stronger than either side's word. This is a
  peer-verified data layer — the thing a state platform provides, built from trading partners.
- **Tamper evidence:** every passport version is hashed and anchored on the testnet; a lender
  verifies authenticity without trusting the SME or us.
- **Consent and expiry:** the SME grants a specific lender time-limited access to a specific
  scope; every view is logged.
- **Pluggable "state adapter":** a connector interface shaped like China's platform fields, so
  when Bangladesh opens official data sharing it plugs straight in. For the demo it runs
  against a mock, clearly labelled.

Difference from DuitDuit's "Passport": ours is counterparty-attested, mobile-money native,
on-chain anchored, and doubles as the state-data substitute.

---

## Cross-check — every Nobo point is in

| # | Nobo's point (abridged) | Where | Status |
| --- | --- | --- | --- |
| N1 | Weekly/quarterly expected vs reality → decisions | C | IN |
| N2 | Automated ledger-based messages (buyers, lenders, sellers) | B | PARTIAL |
| N3 | Market watch, price-drop alerts, vendor/route recommendation | B | IN (reduced, 20 Oct) |
| N4 | Quarterly/annual auto lender report + simulated future | C | IN |
| N5 | Typed facts, not loose text | D | IN |
| N6 | Anonymised inputs | D | IN |
| N7 | Code does financial maths; results from code | D | IN |
| N8 | Multi-agent: main + sub-agents + specialised symbolic checker | D | IN |
| N9 | Multi-model agreement over stated confidence | D | IN |
| N10 | Self-loops with stressed inputs and test cases | D | IN |
| N11 | Dedicated flaw-finder agent beside the checker | D | IN |
| N12 | Multi-variable simulations → suggest path | C | IN |
| N13 | Clickable numbers → formula + source transactions | D | IN |
| N14 | Liquidity mesh + testnet hash of netting rounds | A | IN |
| N15 | Forecast evaluated on unseen data | D | IN |
| N16 | Decision stability score (stress + noise, ~10 variations) | C | IN |
| N17 | Required "I don't know" (agreement, data check, stakes, specific asks, log) | D | IN |
| N18 | Privacy by anonymisation tokens | D | IN |
| N19 | Negotiation when choosing a buyer, with breakdowns | B | IN (reduced, 20 Oct) |
| N20 | Online lender check via track record (mesh) | A | IN |
| Q1 | Uneven cash flow + alert system | B | IN |
| Q2 | Unpaid receivables: causes + tackling | B | IN |
| Q3 | Spot cash gaps before they happen | B | IN |
| Q4 | State data platform problem | A | IN |

20 of 20 points and 4 of 4 questions placed. 14 proposals awaiting approval (3 marked MUST).
