import { useUpdateBill } from "@stark/api/mutations";
import type { Bill } from "@stark/api/types";
import { DialogDescription, DialogHeader, DialogTitle } from "@stark/ui/components/dialog";
import { Field, FieldLabel } from "@stark/ui/components/field";
import { Input } from "@stark/ui/components/input";
import { type SubmitEvent, useId, useState } from "react";
import { BillDialogFooter } from "@/components/bills/bill-dialog-footer";
import { BillEditError } from "@/components/bills/bill-edit-error";

export function RenameBillForm({ bill, onDone }: { bill: Bill; onDone: () => void }) {
  const [label, setLabel] = useState(bill.label);
  const update = useUpdateBill(bill.id);
  const id = useId();

  const handleRename = (event: SubmitEvent<HTMLFormElement>) => {
    event.preventDefault();
    update.mutate({ label: label.trim() }, { onSuccess: onDone });
  };

  return (
    <form className="m-0 grid gap-4" onSubmit={handleRename}>
      <DialogHeader>
        <DialogTitle>Rename bill</DialogTitle>
        <DialogDescription>This is the name Stark uses when it talks about it.</DialogDescription>
      </DialogHeader>
      <Field>
        <FieldLabel htmlFor={id} className="text-sm font-medium text-fg-2">
          Bill name
        </FieldLabel>
        <Input id={id} value={label} onChange={(e) => setLabel(e.target.value)} autoFocus />
        {update.error ? <BillEditError error={update.error} /> : null}
      </Field>
      <BillDialogFooter disabled={!label.trim() || update.isPending} pending={update.isPending}>
        Save
      </BillDialogFooter>
    </form>
  );
}
