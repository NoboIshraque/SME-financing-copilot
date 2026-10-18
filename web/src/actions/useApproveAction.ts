// Approve one action card. The idempotency key is made once per card and reused on every retry,
// so a double tap or a flaky network can never approve the same action twice.
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useRef } from "react";

import type { ActionCard } from "../api/contracts";
import { api } from "../api/endpoints";

export function newIdempotencyKey(): string {
  return globalThis.crypto.randomUUID();
}

export function useApproveAction(card: ActionCard) {
  const queryClient = useQueryClient();
  const key = useRef<string | null>(null);
  return useMutation({
    mutationFn: (stepUpCode?: string) => {
      key.current ??= newIdempotencyKey();
      return api.actions.approve(card.id, { idempotencyKey: key.current, stepUpCode });
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["approvals"] });
    },
  });
}
