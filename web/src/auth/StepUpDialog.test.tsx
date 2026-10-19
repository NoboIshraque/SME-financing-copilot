import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";

import { ApiRequestError } from "../api/client";
import { StepUpDialog } from "./StepUpDialog";

function Harness({ onConfirm }: { onConfirm: (code: string) => Promise<unknown> }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button type="button" onClick={() => setOpen(true)}>
        Approve payment
      </button>
      <StepUpDialog open={open} summary="Pay Supplier 2 ৳82,618" onConfirm={onConfirm} onClose={() => setOpen(false)} />
    </>
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
});
