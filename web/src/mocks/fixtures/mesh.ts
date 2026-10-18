// Mock WP-08 output: the universe's circular debt ring (data/synthetic/universe/
// mesh_obligations.csv) and its netting round, as in the contract examples: Tk 11.5 lakh of debt
// cleared with Tk 1.3 lakh of cash. Only a salted SHA-256 digest is ever anchored.
import type { MeshObligation, NettingRound } from "../../api/contracts";
import type { MeshGraph } from "../../api/types";
import { NOW, money } from "./common";

export const MESH_LABELS: Record<string, string> = {
  sme_fabric: "Islampur Fabric House",
  sme_garment: "Ashulia Stitch Works",
  sme_hardware: "Nawabpur Hardware Traders",
};

const RING: MeshObligation[] = [
  { id: "RING-FG-001", debtor_tenant: "sme_garment", creditor_tenant: "sme_fabric", amount: money(450000), due_date: "2026-10-12", status: "in_round", attested: true, data_mode: "synthetic" },
  { id: "RING-GH-001", debtor_tenant: "sme_hardware", creditor_tenant: "sme_garment", amount: money(320000), due_date: "2026-10-15", status: "in_round", attested: true, data_mode: "synthetic" },
  { id: "RING-HF-001", debtor_tenant: "sme_fabric", creditor_tenant: "sme_hardware", amount: money(380000), due_date: "2026-10-10", status: "in_round", attested: false, data_mode: "synthetic" },
];

export function meshGraph(tenant: string): MeshGraph {
  const mine = RING.filter((o) => o.debtor_tenant === tenant || o.creditor_tenant === tenant);
  // A tenant sees the whole ring only when it is part of it.
  return { obligations: mine.length > 0 ? RING : [], labels: mine.length > 0 ? MESH_LABELS : {} };
}

export function initialRounds(): NettingRound[] {
  return [
    {
      id: "round-2026-10",
      obligation_ids: ["RING-FG-001", "RING-GH-001", "RING-HF-001"],
      participants: ["sme_fabric", "sme_garment", "sme_hardware"],
      settlements: [
        { payer_tenant: "sme_garment", payee_tenant: "sme_fabric", amount: money(70000) },
        { payer_tenant: "sme_garment", payee_tenant: "sme_hardware", amount: money(60000) },
      ],
      gross_total: money(1150000),
      net_total: money(130000),
      status: "proposed",
      approvals: { sme_fabric: true },
      created_at: NOW,
      expires_at: "2026-10-02T18:00:00Z",
      data_mode: "synthetic",
    },
    {
      id: "round-2026-08",
      obligation_ids: ["RING-FG-000", "RING-GH-000", "RING-HF-000"],
      participants: ["sme_fabric", "sme_garment", "sme_hardware"],
      settlements: [{ payer_tenant: "sme_hardware", payee_tenant: "sme_fabric", amount: money(45000) }],
      gross_total: money(610000),
      net_total: money(45000),
      status: "settled",
      approvals: { sme_fabric: true, sme_garment: true, sme_hardware: true },
      created_at: "2026-08-20T10:00:00Z",
      expires_at: "2026-08-22T10:00:00Z",
      anchor: {
        chain: "sepolia",
        digest: "9f2c4e7a1b3d5f60718293a4b5c6d7e8f90123456789abcdef0123456789abcd",
        tx_hash: "0x5e1d3a7c9b2f4e6a8c0d1e2f3a4b5c6d7e8f9a0b1c2d3e4f5a6b7c8d9e0f1a2b",
        block_number: 6543210,
        explorer_url: null,
        anchored_at: "2026-08-21T09:12:00Z",
      },
      data_mode: "synthetic",
    },
  ];
}
