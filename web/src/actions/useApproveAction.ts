// Acting on action cards through the real flows: EXECUTE cards go through WP-11 approvals
// (request -> the owner approves with a fresh code -> execute); DRAFT cards approve the message
// draft they carry (WP-12). Keys are made once per card and reused on every retry, so a double
// tap or a flaky network can never approve or execute the same action twice.
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useRef } from "react";

import type { ActionCard } from "../api/contracts";
import { api } from "../api/endpoints";

export function newIdempotencyKey(): string {
  return globalThis.crypto.randomUUID();
}

/** Owner: approve (requesting first unless `approvalId` exists) and execute, with the code. */
export function useApproveAndExecute(card: ActionCard, approvalId?: string) {
  const queryClient = useQueryClient();
  const progress = useRef<{ requestKey: string; executeKey: string; approvalId?: string; approved?: boolean } | null>(null);
  return useMutation({
    mutationFn: async (stepUpCode: string) => {
      progress.current ??= { requestKey: newIdempotencyKey(), executeKey: newIdempotencyKey(), approvalId };
      const state = progress.current;
      state.approvalId ??= (await api.approvals.request(card, state.requestKey)).approval.id;
      if (!state.approved) {
        await api.approvals.approve(state.approvalId, stepUpCode);
        state.approved = true;
      }
      return api.approvals.execute(state.approvalId, state.executeKey);
    },
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["approvals"] }),
  });
}

/** Accountant: ask the owner to approve an EXECUTE card. */
export function useRequestApproval(card: ActionCard) {
  const queryClient = useQueryClient();
  const key = useRef<string | null>(null);
  return useMutation({
    mutationFn: () => api.approvals.request(card, (key.current ??= newIdempotencyKey())),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["approvals"] }),
  });
}

/** DRAFT card carrying a message draft: approve that draft. The message leaves DecisionGuard once
 * approved, so the API treats it as EXECUTE: the owner confirms with a fresh code. */
export function useApproveDraft(draftId: string | null) {
  const queryClient = useQueryClient();
  const key = useRef<string | null>(null);
  return useMutation({
    mutationFn: (stepUpCode: string) =>
      api.messages.approve(draftId ?? "", { idempotencyKey: (key.current ??= newIdempotencyKey()), stepUpCode }),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["messages"] }),
  });
}
