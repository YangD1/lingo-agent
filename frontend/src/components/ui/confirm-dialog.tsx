"use client";

import { AlertDialog } from "@base-ui/react/alert-dialog";
import { useTranslations } from "next-intl";
import { type ReactElement, useState } from "react";

import { Button } from "@/components/ui/button";

/**
 * Confirmation for actions that can't be undone, like clearing a whole list (component-spec
 * §15). `trigger` is the button that opens it; the dialog closes before `onConfirm` runs, so
 * the page shows progress and errors the way it does for any other action.
 */
export function ConfirmDialog({
  trigger,
  title,
  description,
  confirmLabel,
  onConfirm,
}: {
  trigger: ReactElement;
  title: string;
  description?: string;
  /** Defaults to "Delete". */
  confirmLabel?: string;
  onConfirm: () => void;
}) {
  const t = useTranslations("confirm");
  const [open, setOpen] = useState(false);
  return (
    <AlertDialog.Root open={open} onOpenChange={setOpen}>
      <AlertDialog.Trigger render={trigger} />
      <AlertDialog.Portal>
        <AlertDialog.Backdrop className="fixed inset-0 z-50 bg-foreground/32 transition-opacity duration-150 data-ending-style:opacity-0 data-starting-style:opacity-0" />
        <AlertDialog.Popup className="fixed top-1/2 left-1/2 z-50 w-[420px] max-w-[calc(100%-32px)] -translate-x-1/2 -translate-y-1/2 rounded-xl border bg-popover text-popover-foreground shadow-(--shadow-pop) outline-none transition-[opacity,scale] duration-150 data-ending-style:scale-95 data-ending-style:opacity-0 data-starting-style:scale-95 data-starting-style:opacity-0">
          <div className="flex flex-col gap-1.5 px-[22px] pt-[22px] pb-2">
            <AlertDialog.Title className="text-base font-semibold">{title}</AlertDialog.Title>
            {description && (
              <AlertDialog.Description className="text-[13px] text-muted-foreground">
                {description}
              </AlertDialog.Description>
            )}
          </div>
          <div className="flex justify-end gap-2 px-[22px] pt-4 pb-5">
            <AlertDialog.Close render={<Button variant="ghost" />}>{t("cancel")}</AlertDialog.Close>
            <Button
              variant="danger"
              onClick={() => {
                setOpen(false);
                onConfirm();
              }}
            >
              {confirmLabel ?? t("delete")}
            </Button>
          </div>
        </AlertDialog.Popup>
      </AlertDialog.Portal>
    </AlertDialog.Root>
  );
}
