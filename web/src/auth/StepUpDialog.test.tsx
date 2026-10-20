import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";

import { ApiRequestError } from "../api/client";
import { api } from "../api/endpoints";
import type { Session } from "../api/types";
import { SESSION_KEY } from "./session";
import { StepUpDialog } from "./StepUpDialog";

function Harness({ onConfirm, session = null }: { onConfirm: (code: string) => Promise<unknown>; session?: Session | null }) {
  const [open, setOpen] = useState(false);
  const [client] = useState(() => {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    if (session) queryClient.setQueryData(SESSION_KEY, session);
    return queryClient;
  });
  return (
    <QueryClientProvider client={client}>
      <button type="button" onClick={() => setOpen(true)}>
        Approve payment
      </button>
      <StepUpDialog open={open} summary="Pay Supplier 2 ৳82,618" onConfirm={onConfirm} onClose={() => setOpen(false)} />
    </QueryClientProvider>
  );
}

describe("step-up dialog", () => {
  it("passes the normalised code to the action and closes when it succeeds", async () => {
    const user = userEvent.setup();
    const onConfirm = vi.fn().mockResolvedValue(undefined);
    render(<Harness onConfirm={onConfirm} />);
    await user.click(screen.getByRole("button", { name: "Approve payment" }));

    const dialog = screen.getByRole("dialog", { name: "Confirm it's you" });
    expect(within(dialog).getByText("Pay Supplier 2 ৳82,618")).toBeInTheDocument();
    expect(within(dialog).getByLabelText("6-digit code")).toHaveFocus();
    await user.type(within(dialog).getByLabelText("6-digit code"), "２４６ ８１０");
    await user.click(within(dialog).getByRole("button", { name: "Approve" }));

    expect(onConfirm).toHaveBeenCalledWith("246810");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("stays open and says nothing was approved when the server rejects the code", async () => {
    const user = userEvent.setup();
    const onConfirm = vi
      .fn()
      .mockRejectedValue(new ApiRequestError(401, { code: "invalid_step_up", message_key: "error.invalid_step_up" }));
    render(<Harness onConfirm={onConfirm} />);
    await user.click(screen.getByRole("button", { name: "Approve payment" }));
    await user.type(screen.getByLabelText("6-digit code"), "111111");
    await user.click(screen.getByRole("button", { name: "Approve" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("The code was not accepted, so nothing was approved.");
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });

  it("closes on Escape without running the action and returns focus to the opener", async () => {
    const user = userEvent.setup();
    const onConfirm = vi.fn();
    render(<Harness onConfirm={onConfirm} />);
    const opener = screen.getByRole("button", { name: "Approve payment" });
    await user.click(opener);
    await user.keyboard("{Escape}");

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(onConfirm).not.toHaveBeenCalled();
    expect(opener).toHaveFocus();
  });

  it("shows the signed-in demo owner's current code, and no other account's", async () => {
    const user = userEvent.setup();
    const session = {
      principal: { user_id: "u-garment", tenant_id: "sme_garment", role: "owner", scopes: [], expires_at: null },
      display_name: "Owner", business_name: "Garment Shop", totp_enrolled: true, data_mode: "synthetic",
    } as Session;
    vi.spyOn(api.auth, "demoAccounts").mockResolvedValue([
      { email: "a@demo", password: "x", role: "accountant", business_name: "Garment Shop", totp_hint: "111111" },
      { email: "b@demo", password: "x", role: "owner", business_name: "Fabric Shop", totp_hint: "222222" },
      { email: "c@demo", password: "x", role: "owner", business_name: "Garment Shop", totp_hint: "482913" },
    ]);
    render(<Harness onConfirm={vi.fn()} session={session} />);
    await user.click(screen.getByRole("button", { name: "Approve payment" }));

    expect(await screen.findByText("Demo code: 482913")).toBeInTheDocument();
    expect(screen.queryByText(/111111|222222/)).not.toBeInTheDocument();
  });
});
