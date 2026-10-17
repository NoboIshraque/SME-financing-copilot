"""One valid, realistic example of every contract.

Used by the round-trip tests, by docs, and as mock data for the web client (WP-14).
A test fails if a contract has no example here, so adding a contract means adding one.
All examples are synthetic.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from pydantic import BaseModel

from app.contracts import agents as ag
from app.contracts import analysis as an
from app.contracts import cash as ca
from app.contracts import common as co
from app.contracts import facts as fa
from app.contracts import financing as fi
from app.contracts import ingest as ig
from app.contracts import ledger as le
from app.contracts import market as ma
from app.contracts import mesh as me
from app.contracts import messaging as ms
from app.contracts import party as pa
from app.contracts import reports as re
from app.contracts import security as se

S = co.DataMode.synthetic
NOW = datetime(2026, 9, 30, 18, 0, tzinfo=UTC)
TODAY = date(2026, 9, 30)
TENANT = "sme_grocery"
HEX = "a" * 64
HEX2 = "b" * 64


def tk(value: str | int) -> co.Money:
    return co.Money.of(value)


def examples() -> dict[str, BaseModel]:
    period = co.Period(start=date(2026, 9, 1), end=date(2026, 9, 30))
    provenance = fa.Provenance(
        formula_id="cash.closing_balance",
        formula_version=1,
        input_fact_ids=("fact-opening", "fact-net-flow"),
        source_row_ids=("bank_statement.csv#L812",),
    )
    figure = fa.Figure(
        id="fig-closing-sep",
        label_key="cash.closing_balance",
        value=Decimal("427842.00"),
        unit=fa.Unit.BDT,
        provenance=provenance,
        data_mode=S,
    )
    action = ag.ActionCard(
        id="act-1",
        title_key="action.retime_payable",
        action_type=ag.ActionType.retime_payable,
        tier=co.Tier.DRAFT,
        payload={"bill_id": "sme_grocery:GRO-BILL-00117", "new_date": "2026-10-14"},
        figures=(figure,),
    )
    stability = an.StabilityReport(
        recommendation_id="rec-1",
        baseline_choice="retime_payable",
        results=(
            an.VariationResult(name="sales_minus_20", kind=an.VariationKind.stress,
                               choice="retime_payable", held=True),
            an.VariationResult(name="rows_shuffled", kind=an.VariationKind.noise,
                               choice="retime_payable", held=True),
        ),
        score=Decimal(1),
    )
    agreement = ag.AgreementReport(
        question="Which lever closes the gap at lowest cost?",
        votes=(
            ag.Vote(model="gemini:flash", choice="retime_payable"),
            ag.Vote(model="groq:gpt-oss-120b", choice="retime_payable"),
        ),
        winning_choice="retime_payable",
        agreement_rate=Decimal(1),
        threshold=Decimal("0.67"),
        stakes="medium",
    )
    claim = ag.Claim(
        id="claim-1",
        text="Closing balance on 30 Sep was Tk 427,842.",
        value=Decimal("427842.00"),
        unit=fa.Unit.BDT,
        formula_id="cash.closing_balance",
        input_fact_ids=("fact-opening", "fact-net-flow"),
    )
    gap = ca.CashGap(
        first_breach_day=date(2026, 10, 31),
        lead_time_days=31,
        probability=Decimal("0.34"),
        expected_shortfall=tk(48500),
        worst_day=date(2026, 11, 1),
        drivers=(
            ca.GapDriver(kind=ca.DriverKind.obligation, label_key="driver.salary",
                         amount=tk(60000), reference_id="sme_grocery:OBL-2"),
        ),
    )
    product = fi.FinancingProduct(
        id="bd-example-sme-wc",
        provider="Example Bank PLC",
        name="CMSME working capital (example)",
        kind=fi.ProductKind.working_capital,
        rate_type=fi.RateType.reducing_balance,
        nominal_rate_pa=Decimal("12.5"),
        fees=(fi.Fee(name="processing", kind=fi.FeeKind.percent_of_principal,
                     value=Decimal("0.5")),),
        min_amount=tk(50000),
        max_amount=tk(5000000),
        min_tenor_days=90,
        max_tenor_days=365,
        rules=(
            fi.EligibilityRule(id="age", metric="business_age_months", op=fi.RuleOp.gte,
                               threshold=Decimal(24), description_key="rule.business_age"),
        ),
        source_url="https://example.org/sme-loan",
        checked_on=date(2026, 10, 18),
        data_mode=co.DataMode.public,
    )
    eligibility = fi.Eligibility(
        product_id=product.id,
        status=fi.EligibilityStatus.pass_,
        reasons=(
            fi.EligibilityReason(rule_id="age", status=fi.EligibilityStatus.pass_,
                                 observed_value=Decimal(74), message_key="rule.business_age"),
        ),
    )
    anchor = me.AnchorReceipt(chain=me.AnchorChain.offline, digest=HEX, anchored_at=NOW)
    transaction = le.Transaction(
        id="sme_grocery-T000001",
        tenant_id=TENANT,
        occurred_at=NOW,
        amount=tk(850),
        direction=le.Direction.inflow,
        channel=le.Channel.bkash,
        category=le.TxCategory.sales,
        counterparty_token="PARTY_0123456789",
        source_ref="transactions_truth.csv#L2",
        data_mode=S,
    )
    invoice = le.Invoice(
        id="sme_grocery:GRO-INV-00001",
        tenant_id=TENANT,
        counterparty_token="PARTY_abcdef0123",
        issue_date=date(2026, 9, 10),
        due_date=date(2026, 9, 25),
        amount=tk(4200),
        amount_paid=tk(0),
        status=le.DocumentStatus.open,
        source_ref="baki_register.csv#L2",
        data_mode=S,
    )
    bill = le.Bill(
        id="sme_grocery:GRO-BILL-00001",
        tenant_id=TENANT,
        counterparty_token="PARTY_fedcba9876",
        issue_date=date(2026, 9, 5),
        due_date=date(2026, 9, 12),
        amount=tk(150000),
        amount_paid=tk(150000),
        status=le.DocumentStatus.paid,
        paid_date=date(2026, 9, 12),
        source_ref="bills_register.csv#L2",
        data_mode=S,
    )
    passport_evidence = re.EvidenceItem(kind=re.EvidenceKind.bank_statement, digest=HEX,
                                        period=period, verified=True)
    out: list[BaseModel] = [
        tk("1250.50"),
        period,
        co.ApiError(code="not_found", message_key="error.not_found"),
        pa.Party(id="sme_grocery:PARTY_0123456789", tenant_id=TENANT,
                 token="PARTY_0123456789", role=pa.PartyRole.customer,
                 display_label="Customer 1", data_mode=S),
        transaction,
        invoice,
        bill,
        le.RecurringObligation(id="sme_grocery:OBL-1", tenant_id=TENANT,
                               kind=le.ObligationKind.rent, counterparty_token="PARTY_1111111111",
                               amount=tk(35000), frequency=le.Frequency.monthly, day_of_period=5,
                               start_date=date(2025, 4, 1), source_ref="obligations.csv#L2",
                               data_mode=S),
        fa.FormulaRef(formula_id="cash.closing_balance", version=1,
                      expression="opening_balance + inflows - outflows"),
        provenance,
        fa.Fact(id="fact-opening", tenant_id=TENANT, metric="opening_balance",
                value=Decimal("402000.00"), unit=fa.Unit.BDT, period=period,
                source_refs=("bank_statement.csv#L700",), data_mode=S),
        figure,
        fa.ExplainedInput(fact_id="fact-opening", metric="opening_balance",
                          value=Decimal("402000.00"), unit=fa.Unit.BDT),
        fa.Explanation(
            figure_id=figure.id,
            formula=fa.FormulaRef(formula_id="cash.closing_balance", version=1,
                                  expression="opening_balance + inflows - outflows"),
            value=figure.value, unit=fa.Unit.BDT,
            inputs=(fa.ExplainedInput(fact_id="fact-opening", metric="opening_balance",
                                      value=Decimal("402000.00"), unit=fa.Unit.BDT),),
            source_rows=("bank_statement.csv#L812",), masked=False,
        ),
        ma.PricePoint(commodity="rice_coarse", unit="kg", price=tk(58), low=tk(55), high=tk(60),
                      market="Dhaka", source=ma.PriceSource.tcb, observed_on=TODAY,
                      data_mode=co.DataMode.public),
        ma.VendorQuote(vendor_token="PARTY_2222222222", commodity="rice_coarse", unit="kg",
                       unit_price=tk(56), delivery_cost=tk(400), lead_time_days=2,
                       on_time_rate=Decimal("0.9"), quoted_on=TODAY, data_mode=S),
        an.Ratio(name="current_ratio", value=Decimal("1.42"), unit=fa.Unit.ratio, period=period,
                 provenance=provenance),
        an.Variance(metric="net_sales", period=period, expected=Decimal("780000"),
                    actual=Decimal("741000"), unit=fa.Unit.BDT, rank=1),
        an.Scenario(id="sc-1", name_key="scenario.sales_minus_20",
                    assumptions={"sales_change_pct": Decimal(-20)}, expected_outcome=tk(310000),
                    worst_5pct_outcome=tk(95000), p_buffer_breach=Decimal("0.12"), paths=1000,
                    seed=7),
        stability.results[0],
        stability,
        claim,
        ag.CheckResult(claim_id="claim-1", status=ag.CheckStatus.verified,
                       recomputed_value=Decimal("427842.00")),
        agreement.votes[0],
        agreement,
        ag.Abstention(reason=ag.AbstentionReason.insufficient_data,
                      missing=("at least 90 days of sales history",),
                      message_key="abstain.insufficient_data"),
        action,
        ag.Recommendation(id="rec-1", tenant_id=TENANT, question="Can I pay rent on time?",
                          answer_text="Yes if the supplier bill moves to 14 Oct.",
                          claims=(claim,), action_cards=(action,), agreement=agreement,
                          stability=stability, critic_objection="Supplier may refuse.",
                          data_mode=S, created_at=NOW),
        ca.ForecastPoint(day=date(2026, 10, 1), p10=tk(380000), p50=tk(420000), p90=tk(455000),
                         p_below_buffer=Decimal("0.02")),
        ca.ForecastBand(
            tenant_id=TENANT, as_of=TODAY, horizon_days=1, paths=1000, seed=7,
            opening_balance=tk(427842), buffer=tk(100000),
            points=(ca.ForecastPoint(day=date(2026, 10, 1), p10=tk(380000), p50=tk(420000),
                                     p90=tk(455000), p_below_buffer=Decimal("0.02")),),
            data_mode=S, generated_at=NOW,
        ),
        gap.drivers[0],
        gap,
        ca.Alert(id="al-1", tenant_id=TENANT, tier=ca.AlertTier.warning,
                 title_key="alert.gap_ahead", gap=gap, fixes=(action,),
                 dedupe_key="gap:2026-10-31", created_at=NOW, data_mode=S),
        ca.SmoothingLever(kind=ca.LeverKind.retime_payable, gap_reduction=tk(150000),
                          cost=tk(0), action=action),
        product.fees[0],
        product.rules[0],
        product,
        fi.FinancingNeed(tenant_id=TENANT, amount=tk(200000), needed_by=date(2026, 10, 25),
                         tenor_days=180),
        eligibility.reasons[0],
        eligibility,
        fi.FinancingOption(product=product, eligibility=eligibility,
                           effective_apr=Decimal("13.62"), total_cost=tk(13400),
                           p_buffer_breach=Decimal("0.05"), speed_days=10,
                           approval_likelihood=Decimal("0.6"), score=Decimal(81), rank=1),
        fi.LenderProfile(lender_id="lender-example", name="Example Bank PLC",
                         licence_status=fi.LicenceStatus.licensed, regulator="Bangladesh Bank",
                         events_count=12, quoted_vs_realised_apr_gap=Decimal("0.4"),
                         median_disbursal_days=Decimal(9), data_mode=S),
        me.MeshObligation(id="RING-FG-001", debtor_tenant="sme_garment",
                          creditor_tenant="sme_fabric", amount=tk(450000),
                          due_date=date(2026, 10, 12), data_mode=S),
        me.Settlement(payer_tenant="sme_garment", payee_tenant="sme_fabric", amount=tk(70000)),
        anchor,
        me.NettingRound(
            id="round-1",
            obligation_ids=("RING-FG-001", "RING-GH-001", "RING-HF-001"),
            participants=("sme_fabric", "sme_garment", "sme_hardware"),
            settlements=(
                me.Settlement(payer_tenant="sme_garment", payee_tenant="sme_fabric",
                              amount=tk(70000)),
                me.Settlement(payer_tenant="sme_garment", payee_tenant="sme_hardware",
                              amount=tk(60000)),
            ),
            gross_total=tk(1150000), net_total=tk(130000),
            status=me.RoundStatus.proposed, approvals={"sme_fabric": True},
            created_at=NOW, expires_at=NOW + timedelta(hours=48), data_mode=S,
        ),
        me.Attestation(id="att-1", obligation_id="RING-FG-001", attester_tenant="sme_garment",
                       kind=me.AttestationKind.confirm, digest=HEX, created_at=NOW),
        se.Principal(user_id="u-owner", tenant_id=TENANT, role=se.Role.owner),
        se.Approval(id="ap-1", tenant_id=TENANT, action_card_id="act-1", tier=co.Tier.EXECUTE,
                    requested_by="copilot", decided_by="u-owner",
                    status=se.ApprovalStatus.approved, step_up_verified=True,
                    idempotency_key="idem-0001", created_at=NOW,
                    expires_at=NOW + timedelta(hours=24)),
        se.AuditEvent(seq=1, tenant_id=TENANT, at=NOW, actor="u-owner", action="approve",
                      tier=co.Tier.EXECUTE, target="act-1", details_digest=HEX,
                      prev_hash=se.GENESIS_HASH, hash=HEX2),
        ms.MessageDraft(id="msg-1", tenant_id=TENANT, template_id="pre_due_reminder.v1",
                        purpose=ms.MessagePurpose.pre_due_reminder, language=co.Language.bn,
                        channel=ms.MessageChannel.copy, recipient_token="PARTY_abcdef0123",
                        body="Customer 1, your payment of Tk 4,200 is due on 25 Sep.",
                        variables={"amount": "4200.00", "due_date": "2026-09-25"},
                        tier=co.Tier.DRAFT, created_at=NOW, data_mode=S),
        ig.UnparsedRow(row_ref="bkash.csv#L19", reason_key="ingest.bad_date",
                       raw_excerpt="31/02/2026 ..."),
        ig.DraftRow(row_ref="photo-1#line3", confidence=Decimal("0.62"), invoice=invoice,
                    flagged=True),
        ig.IngestPreview(preview_id="pv-1", tenant_id=TENANT,
                         source_format=ig.SourceFormat.bkash_statement, file_digest=HEX,
                         transactions=(transaction,), data_mode=S),
        passport_evidence,
        re.PassportVersion(id="pp-1", tenant_id=TENANT, version=1, issued_at=NOW,
                           evidence=(passport_evidence,), attestations_confirmed=3,
                           attestations_disputed=0, digest=HEX, anchor=anchor, data_mode=S),
        re.ShareGrant(id="grant-1", tenant_id=TENANT, passport_id="pp-1",
                      lender_label="Lender 1", scopes=("passport:read",), created_at=NOW,
                      expires_at=NOW + timedelta(days=7)),
        re.VerifyResult(passport_id="pp-1", recomputed_digest=HEX, anchored_digest=HEX,
                        valid=True, checked_on=TODAY),
    ]
    found: dict[str, BaseModel] = {}
    for item in out:
        found.setdefault(type(item).__name__, item)
    return found
