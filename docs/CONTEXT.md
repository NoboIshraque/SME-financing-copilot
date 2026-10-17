# Context — everything we learned before building

Source of truth for *why* we build what we build. Full research brief (with sources):
the Claude Doc "SME Finance Copilot — Research Brief"
(https://claude.ai/code/artifact/5f6743d8-8966-4c29-aea2-1d0f737b609c).

## 1. Competition facts (from the official guidelines)

- **Event:** 2026 Shenzhen International FinTech Competition (FinTechathon), International Track.
  Hosts: Tsinghua University PBC School of Finance with WeBank. Theme: **"AI as a Financial
  Participant"** — each team builds an AI agent that completes real tasks in a financial scenario.
- **Topic E — SME Finance Copilot:** a finance copilot for small-business owners, offering
  financing-option matching, cash-flow management with alerts, and business financial analysis.
- **Scoring (same for all topics):** Task completion **40%** · Security & compliance **30%** ·
  Innovation & interaction **30%** · challenge bonus (on-chain exploration) **0–5 points**.
- **Deliverables:** (01) technical documentation — architecture, core algorithms, security design;
  (02) presentation deck ≤ 10 min; (03) demo video ≤ 5 min, "optional"; (04) source code with
  README, GitHub link, deployment instructions, test cases; (05) security self-assessment —
  permission-tier implementation and known-risk list; (06) execution evidence — for non-on-chain
  topics, simulated-account/sandbox operation logs **and demo video**. So the video is required in practice.
- **Deadline:** registration and submission both close **20 Oct 2026, 23:59 Beijing (21:59 Dhaka)**.
  Submissions can be updated until then; the latest counts.
- **Eligibility:** full-time students at universities outside Mainland China, HK, Macao, Chinese
  Taipei; teams of 2–5; ≥ 60% non-Chinese nationals; one team per person. **Language: English.**
- **Timeline after:** online review 20–31 Oct; finalists announced 31 Oct; Shenzhen final 21–23 Nov.
  Prizes: RMB 100k / 80k / 50k, Best Innovation RMB 20k. Finalists' travel covered.
- **Our team:** Nobo Ishraque, Amdad, Labib (BUP, Bangladesh).

## 2. The problem — numbers worth quoting (sources in the research brief)

- SMEs ≈ 90% of businesses and > 50% of employment worldwide; MSME finance gap **$5.7T**
  ($8T with informal firms) — IFC.
- US: 51% of employer firms cite uneven cash flow, 56% struggle to pay operating expenses (Fed SBCS).
- 39% of US owners say one late payment threatened payroll or bills (QuickBooks 2026).
- China: 71% of 9,252 surveyed small firms had unpaid receivables, averaging ~RMB 103,000 —
  about two-thirds of quarterly income (Peking University survey via SCMP).
- Bangladesh: CMSME finance gap ≈ **$2.8B**; ~36% of enterprises have formal finance; women-led
  firms get 7.28% of CMSME credit; collateral and weak bookkeeping are the main blockers.
- Proof data-driven lending works: WeBank Weiyedai 1.8M+ clients, RMB 1.8T; MYbank "3-1-0";
  bKash–BRAC merchant loans up to Tk 50,000 in about a minute; City Bank–bKash nano loans
  Tk 2,300 crore to 950,000 users, default < 1%.
- AI today: QuickBooks agents → paid ~5 days faster; the "12 hours saved" is narrower than it
  sounds. Census: ~24% of US firms use AI in any function; OECD small vs large firms 17.4% vs 52%.
- Kenya RCT (Otis et al., Management Science): GPT-4 mentor → no average effect; high performers
  +15%, low performers −8%. Generic advice hurts the weakest owners.

## 3. Definitions (from the Q&A)

- **Uneven cash flow:** money in and out on different schedules; profitable on paper, broke on rent day.
- **Unpaid receivables:** money customers owe for goods already given on credit (baki).
- **Cash gap:** a window where bills due exceed cash on hand plus money received in that window.
- **Collateral:** an asset pledged to a lender (land deed, building, FDR). Data-driven lending
  replaces "what can we seize?" with "how does money actually move through this business?"
- **State data platform:** China's national financing credit platform pools government-held data
  (74 items: registration, tax, social insurance…) and shows it to lenders with the firm's consent.
  Bangladesh has no equivalent; the CIB records loan history only.
- **Liquidity:** how fast something turns into cash to pay what's due, without losing value. A
  business can be profitable but illiquid.
- **Netting:** offsetting mutual debts so only the difference moves (owe 800, owed 785 → pay 15).
  **Multilateral netting** does it across 3+ parties through a netting centre; CHIPS supports $29
  of payments per $1 of prefunded liquidity. A **netting protocol** sets rules for enforceability,
  scope, cut-offs, defaults, currencies, data quality and audit.
- **Liquidity mesh (Nobo's idea):** a network linking SMEs, buyers, suppliers and lenders so a cash
  gap at one business is filled through the cheapest path — netting first, then buyer early pay,
  supplier terms, then a lender. Caution: moving money directly between SMEs can count as lending
  or deposit-taking (licence needed); route real funding through licensed lenders.

## 4. Why LLMs are unreliable at financial analysis (research, not guesses)

1. **Not calculators.** FAITH benchmark: top models 95.6% on simple lookups → near 0% on
   multi-variable calculations from financial tables. "A 99% accuracy rate yields 0% operational
   trust" (Agand 2026, VeNRA).
2. **Wrong retrieval.** FinanceBench: GPT-4-Turbo + retrieval wrong or refused on 81% of questions.
   Vector search conflates Net Income with Net Sales.
3. **Lost in the middle.** Accuracy drops when the key fact sits mid-context (Liu et al. 2023).
4. **Memorisation passes for skill.** LLMs recall exact pre-cutoff economic data; told to ignore
   it, they don't; post-cutoff directional accuracy only 40% (Lopez-Lira, Tang, Zhu 2025).
5. **Can't self-correct.** Without external feedback, self-correction often makes answers worse
   (Huang et al., ICLR 2024); LLMs can't reliably *find* their errors but can fix one once shown.
6. **Overconfident.** Verbalised confidence is inflated; consistency across samples is a better
   signal (Xiong et al., ICLR 2024).
7. **Built-in biases.** Preference for tech, large caps, contrarian strategies (Lee et al., ICAIF
   2025); 48-model test shows framing/anchoring/herding, and generic debiasing can backfire
   (Keshavarz et al. 2026).
8. **Sycophancy.** RLHF assistants drift toward agreeing with the user (Sharma et al., ICLR 2024).

**What fixes it (research-backed):** let code do the maths (Program of Thoughts, ≈ +12% over CoT
incl. FinQA); typed fact ledger + deterministic Python (VeNRA, ≈ 1.2% hallucination); treat model
claims as proposals and verify symbolically (VeriFin, median 5 ms); small specialist checker
trained on sabotaged records beat 70B+ models (VeNRA Sentinel); consistency-based confidence;
anonymise inputs to cut memorisation.

**Our new ideas (innovation edge — untested, pitch as innovations):**
1. Decision stability score — stress (may change) vs irrelevant noise (must not change); show
   "what would flip this".
2. Nightly audit drill — plant errors in a sandbox ledger copy; publish catch rate as a trust score.
3. "Case against" agent from a different model family.
4. Rails, not chat — pre-checked action cards for weaker owners.
5. Required "I don't know" — measured by agreement + data sufficiency, stakes-tiered, logged.
6. Privacy by anonymisation that also blocks memorisation; optional secret amount scaling.
7. Every number clickable to formula + source rows.
8. SME netting rounds through the liquidity mesh, anchored on a testnet.

Honest caveats: anonymisation isn't bulletproof (LLMs can re-identify from context — strip dates,
places, unusual product names too); tokenising alone isn't novel (DuitDuit does it); free LLM tiers
may train on inputs, so only anonymised data leaves the server.

## 5. Rivals on GitHub (checked 17 Oct 2026)

- **DuitDuit** (Malaysia, ex-FinBrain OS) — the one to beat: 850 tests, 57 eval tasks (30
  adversarial), live site, forecast bands, rule-based matching, review inbox with earned autonomy,
  Financing Readiness Passport, tokenisation, hash-chained audit, simulated bank, EN/MS/ZH.
  Weak: products only "modelled on" real schemes; synthetic data; forecast accuracy not scored on
  demo; pattern-based guardrails (paraphrases unproven); hosted auth untested; judges in China need
  a VPN; very broad scope.
- **OneGate SME** (India, Team GateKeepers): forecast with backtest (MAPE 3.6–14.8% on its own
  synthetic data), 5 Indian products by total cost, GST, mandates/autopilot, OTP, 21-attack red
  team. Weak: **LLM never run live**; in-memory state; API key in git history; open CORS, no CSP.
- **FlowWise** (Vietnam, e-commerce, multi-currency 13-week forecast, no agent) — low maturity.
- **ururu9339/fintechathon-2026** — empty template.
- Unconfirmed: Changeofplans (Thai, live central-bank rates), tuananhpham-vnu/Fintech (lender-side).

**Shared blind spots = our targets:** synthetic data only; formal-SME assumptions; single-firm view
(no mesh); AI reliability asserted not measured; pattern-only guardrails; not reachable from China;
loans-only financing with simulated products; circular accuracy claims; security hygiene slips.

## 6. Data sources we will use

| Need | Source | Notes |
| --- | --- | --- |
| Bangladesh commodity prices (daily) | Trading Corporation of Bangladesh (TCB) Dhaka market prices; AgriPriceBD (Mendeley dataset) | For N3 and market backtests |
| Global raw materials (monthly) | World Bank Commodity Price Data ("Pink Sheet") | |
| Real transactional sales for forecaster backtests | UCI Online Retail II (real retailer transactions) | Walk-forward, never self-generated |
| Bangladesh financing products and rates | Bangladesh Bank circulars/refinance schemes, bank product pages (BRAC, City, Dhaka Bank…), bKash nano-loan pages | Every product row carries a source URL and "checked on" date |
| Prompt-injection training data | Public injection datasets + our generated Bangla/Banglish/Chinese paraphrases | For the classifier (WP-17) |
| Real SME records | 3–5 consenting Dhaka shops (WP-20), anonymised | |

## 7. Product principles (apply everywhere)

1. Code computes, the model narrates. 2. Every number has provenance. 3. Every action has a tier
and an owner. 4. Nothing irreversible without the owner. 5. Prefer abstaining to guessing.
6. Measure every claim we make in the pitch. 7. Label synthetic data as synthetic, always.
8. Built for a Dhaka shop with a phone, not a CFO with an ERP.
