// Liquidity mesh (N14): who owes whom across opted-in businesses, the proposed netting round,
// every party's approval (EXECUTE with step-up), and the testnet anchor of settled rounds.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { newIdempotencyKey } from "../../actions/useApproveAction";
import type { NettingRound } from "../../api/contracts";
import { api } from "../../api/endpoints";
import type { MeshGraph } from "../../api/types";
import { StepUpDialog } from "../../auth/StepUpDialog";
import { useRequiredSession } from "../../auth/session";
import { ErrorState, QueryView } from "../../components/States";
import { useDocumentTitle } from "../../components/useDocumentTitle";
import { useFormat } from "../../i18n/useFormat";

const card = "rounded-2xl bg-white p-4 shadow-sm ring-1 ring-slate-200 dark:bg-slate-900 dark:ring-slate-800";

/** Nodes on a circle, debts as arrows from debtor to creditor. Visual only: the list carries the facts. */
function GraphPicture({ graph }: { graph: MeshGraph }) {
  const format = useFormat();
  const tenants = Object.keys(graph.labels);
  const at = (i: number) => {
    const angle = (2 * Math.PI * i) / tenants.length - Math.PI / 2;
    return { x: 160 + 105 * Math.cos(angle), y: 130 + 95 * Math.sin(angle) };
  };
  const pos = Object.fromEntries(tenants.map((tenant, i) => [tenant, at(i)]));
  return (
    <svg viewBox="0 0 320 260" className="mx-auto mt-2 w-full max-w-sm text-slate-700 dark:text-slate-200" aria-hidden="true">
      <defs>
        <marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
          <path d="M0 0L10 5L0 10z" fill="currentColor" />
        </marker>
      </defs>
      {graph.obligations.map((o) => {
        const from = pos[o.debtor_tenant];
        const to = pos[o.creditor_tenant];
        if (!from || !to) return null;
        const shorten = (a: number, b: number) => a + (b - a) * 0.8;
        return (
          <g key={o.id}>
            <line x1={from.x + (to.x - from.x) * 0.2} y1={from.y + (to.y - from.y) * 0.2} x2={shorten(from.x, to.x)} y2={shorten(from.y, to.y)} stroke="currentColor" strokeWidth={1.5} markerEnd="url(#arrow)" />
            <text x={(from.x + to.x) / 2} y={(from.y + to.y) / 2 - 4} textAnchor="middle" fontSize="11" fill="currentColor">
              {format.money(o.amount)}
            </text>
          </g>
        );
      })}
      {tenants.map((tenant) => {
        const p = pos[tenant];
        if (!p) return null;
        return (
          <g key={tenant}>
            <circle cx={p.x} cy={p.y} r={18} className="fill-teal-600" />
            <text x={p.x} y={p.y + 32} textAnchor="middle" fontSize="11" fill="currentColor">
              {(graph.labels[tenant] ?? tenant).split(" ")[0]}
            </text>
          </g>
        );
      })}
    </svg>
  );
}

function RoundCard({ round, labels }: { round: NettingRound; labels: Record<string, string> }) {
  const { t } = useTranslation();
  const format = useFormat();
  const session = useRequiredSession();
  const queryClient = useQueryClient();
  const [stepUp, setStepUp] = useState(false);
  const key = useRef<string | null>(null);
  const me = session.principal.tenant_id;
  const name = (tenant: string) => labels[tenant] ?? tenant;
  const approve = useMutation({
    mutationFn: (code: string) => {
      key.current ??= newIdempotencyKey();
      return api.mesh.approve(round.id, { idempotencyKey: key.current, stepUpCode: code });
    },
    onSuccess: (updated) => queryClient.setQueryData<NettingRound[]>(["mesh", "rounds"], (rounds) => rounds?.map((r) => (r.id === updated.id ? updated : r))),
  });
  const verify = useMutation({ mutationFn: () => api.mesh.verify(round.id) });
  const approvedByMe = round.approvals?.[me] === true;
  const waiting = round.participants.filter((tenant) => round.approvals?.[tenant] !== true);
  const titleId = `round-${round.id}`;

  return (
    <article aria-labelledby={titleId} className={card}>
      <h4 id={titleId} className="font-semibold">
        {round.status === "settled" ? t("mesh.settledTitle", { date: format.date(round.created_at, "long") }) : t("mesh.proposedTitle")}
      </h4>
      <p className="mt-1 text-lg">
        {t("mesh.clears")} <strong className="tabular-nums">{format.money(round.gross_total)}</strong> {t("mesh.withCash")}{" "}
        <strong className="tabular-nums">{format.money(round.net_total)}</strong>
      </p>
      <ul className="mt-3 space-y-1 text-sm">
        {round.settlements.map((s) => (
          <li key={`${s.payer_tenant}-${s.payee_tenant}`}>
            {t("mesh.pays", { payer: name(s.payer_tenant), payee: name(s.payee_tenant) })} <span className="font-semibold tabular-nums">{format.money(s.amount)}</span>
          </li>
        ))}
      </ul>

      <p className="mt-3 text-sm font-medium">{t("mesh.approvals")}</p>
      <ul className="mt-1 space-y-0.5 text-sm">
        {round.participants.map((tenant) => (
          <li key={tenant} className="flex justify-between gap-2">
            <span>{name(tenant)}{tenant === me ? ` (${t("mesh.you")})` : ""}</span>
            <span className={round.approvals?.[tenant] ? "text-emerald-700 dark:text-emerald-300" : "text-slate-500"}>
              {round.approvals?.[tenant] ? t("mesh.approved") : t("mesh.waiting")}
            </span>
          </li>
        ))}
      </ul>

      {round.status === "proposed" && (
        <div className="mt-4">
          <p className="text-xs text-slate-500 dark:text-slate-400">{t("mesh.expires", { when: format.dateTime(round.expires_at) })}</p>
          {round.participants.includes(me) && !approvedByMe && (
            session.principal.role === "owner" ? (
              <button type="button" onClick={() => setStepUp(true)} className="mt-2 w-full rounded-xl bg-teal-700 px-4 py-3 font-semibold text-white sm:w-auto">
                {t("mesh.approve")}
              </button>
            ) : (
              <p className="mt-2 text-sm">{t("actionCard.ownerOnly")}</p>
            )
          )}
          {approvedByMe && waiting.length > 0 && (
            <p className="mt-2 text-sm">{t("mesh.waitingFor", { names: waiting.map(name).join(", ") })}</p>
          )}
        </div>
      )}

      {round.anchor && (
        <div className="mt-4 rounded-xl bg-slate-50 p-3 text-sm dark:bg-slate-800/60">
          <p className="font-medium">{t(`mesh.chain.${round.anchor.chain}`)}</p>
          {round.anchor.tx_hash && (
            <p className="mt-1 break-all font-mono text-xs">
              {round.anchor.explorer_url ? (
                <a href={round.anchor.explorer_url} target="_blank" rel="noopener noreferrer" className="underline">
                  {t("mesh.tx", { hash: round.anchor.tx_hash })}
                </a>
              ) : (
                t("mesh.tx", { hash: round.anchor.tx_hash })
              )}
            </p>
          )}
          <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">{t("mesh.hashOnly")}</p>
          <button type="button" onClick={() => verify.mutate()} className="mt-2 rounded-lg border border-slate-300 px-3 py-1.5 font-medium dark:border-slate-600">
            {t("mesh.verify")}
          </button>
          {verify.data && (
            <p role="status" className={`mt-2 font-semibold ${verify.data.valid ? "text-emerald-700 dark:text-emerald-300" : "text-red-700 dark:text-red-300"}`}>
              {verify.data.valid ? t("mesh.valid") : t("mesh.invalid")}
            </p>
          )}
          {verify.isError && <ErrorState error={verify.error} />}
        </div>
      )}

      <StepUpDialog
        open={stepUp}
        summary={<p>{t("mesh.stepUpSummary", { gross: format.money(round.gross_total), net: format.money(round.net_total) })}</p>}
        onConfirm={(code) => approve.mutateAsync(code)}
        onClose={() => setStepUp(false)}
      />
    </article>
  );
}

export function MeshScreen() {
  const { t } = useTranslation();
  const format = useFormat();
  useDocumentTitle(t("nav.mesh"));
  const graph = useQuery({ queryKey: ["mesh", "graph"], queryFn: api.mesh.obligations });
  const rounds = useQuery({ queryKey: ["mesh", "rounds"], queryFn: api.mesh.rounds });
  return (
    <section aria-labelledby="h-mesh" className="space-y-6">
      <h2 id="h-mesh" className="text-xl font-semibold">{t("nav.mesh")}</h2>
      <QueryView query={graph} isEmpty={(data) => data.obligations.length === 0} empty={t("mesh.empty")}>
        {(data) => (
          <>
            <section aria-labelledby="h-graph" className={card}>
              <h3 id="h-graph" className="text-lg font-semibold">{t("mesh.graphTitle")}</h3>
              <GraphPicture graph={data} />
              <ul className="mt-2 space-y-1 text-sm">
                {data.obligations.map((o) => (
                  <li key={o.id}>
                    {t("mesh.owes", { debtor: data.labels[o.debtor_tenant] ?? o.debtor_tenant, creditor: data.labels[o.creditor_tenant] ?? o.creditor_tenant })}{" "}
                    <span className="font-semibold tabular-nums">{format.money(o.amount)}</span> · {t("mesh.due", { date: format.date(o.due_date) })}
                    {o.attested && <span className="text-xs text-emerald-700 dark:text-emerald-300"> ({t("mesh.attested")})</span>}
                  </li>
                ))}
              </ul>
            </section>
            <section aria-labelledby="h-rounds" className="space-y-3">
              <h3 id="h-rounds" className="text-lg font-semibold">{t("mesh.roundsTitle")}</h3>
              <QueryView query={rounds} isEmpty={(list) => list.length === 0} empty={t("mesh.noRounds")}>
                {(list) => (
                  <ul className="space-y-3">
                    {list.map((round) => (
                      <li key={round.id}>
                        <RoundCard round={round} labels={data.labels} />
                      </li>
                    ))}
                  </ul>
                )}
              </QueryView>
            </section>
          </>
        )}
      </QueryView>
    </section>
  );
}
