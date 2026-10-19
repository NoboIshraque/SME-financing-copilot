// Accessible modal: focus moves in and is trapped, Escape and the backdrop close it, and focus
// returns to the control that opened it.
import { useEffect, useLayoutEffect, useRef, type ReactNode } from "react";
import { createPortal } from "react-dom";

const FOCUSABLE =
  'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

const PLACEMENT = {
  center: "items-end justify-center sm:items-center",
  right: "items-stretch justify-end",
  left: "items-stretch justify-start",
};

interface DialogProps {
  open: boolean;
  onClose: () => void;
  labelledBy: string;
  describedBy?: string;
  placement?: keyof typeof PLACEMENT;
  panelClassName?: string;
  children: ReactNode;
}

export function Dialog({
  open,
  onClose,
  labelledBy,
  describedBy,
  placement = "center",
  panelClassName = "w-full max-w-md rounded-t-2xl sm:rounded-2xl",
  children,
}: DialogProps) {
  const panelRef = useRef<HTMLDivElement>(null);
  const onCloseRef = useRef(onClose);
  useLayoutEffect(() => {
    onCloseRef.current = onClose;
  });

  useEffect(() => {
    if (!open) return;
    const opener = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const panel = panelRef.current;
    const focusables = () => (panel ? Array.from(panel.querySelectorAll<HTMLElement>(FOCUSABLE)) : []);
    (panel?.querySelector<HTMLElement>("[data-autofocus]") ?? focusables()[0] ?? panel)?.focus();

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        onCloseRef.current();
        return;
      }
      if (event.key !== "Tab") return;
      const items = focusables();
      const first = items[0];
      const last = items[items.length - 1];
      if (!first || !last) return;
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      opener?.focus();
    };
  }, [open]);

  if (!open) return null;
  return createPortal(
    <div className={`fixed inset-0 z-50 flex ${PLACEMENT[placement]}`}>
      <div className="absolute inset-0 bg-slate-900/50" aria-hidden="true" onClick={() => onCloseRef.current()} />
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={labelledBy}
        aria-describedby={describedBy}
        tabIndex={-1}
        className={`relative max-h-dvh overflow-y-auto bg-white p-5 shadow-xl outline-none dark:bg-slate-900 ${panelClassName}`}
      >
        {children}
      </div>
    </div>,
    document.body,
  );
}
