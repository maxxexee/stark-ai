import { useUpdateBill } from "@stark/api/mutations";
import { plansQuery } from "@stark/api/queries";
import type { Bill } from "@stark/api/types";
import { DialogDescription, DialogHeader, DialogTitle } from "@stark/ui/components/dialog";
import { Field, FieldLabel } from "@stark/ui/components/field";
import { useQuery } from "@tanstack/react-query";
import { type SubmitEvent, useId, useState } from "react";
import { BillDialogFooter } from "@/components/bills/bill-dialog-footer";
import { BillEditError } from "@/components/bills/bill-edit-error";
import { PlanSelect } from "@/components/bills/plan-select";

export function ChangePlanForm({
  bill,
  plan,
  onDone,
}: {
  bill: Bill;
  plan: string;
  onDone: () => void;
}) {
  const plans = useQuery(plansQuery(bill.kind === "tv" ? "tv" : "data", bill.provider));
  const [picked, setPicked] = useState(plan);
  const update = useUpdateBill(bill.id);
  const id = useId();

  const handleSavePlan = (event: SubmitEvent<HTMLFormElement>) => {
    event.preventDefault();
    update.mutate({ plan: picked }, { onSuccess: onDone });
  };

  return (
    <form className="m-0 grid gap-4" onSubmit={handleSavePlan}>
      <DialogHeader>
        <DialogTitle>Change plan</DialogTitle>
        <DialogDescription>
          Stark buys this plan from {bill.provider} each time {bill.label} renews.
        </DialogDescription>
      </DialogHeader>
      <Field>
        <FieldLabel htmlFor={id} className="text-sm font-medium text-fg-2">
          Plan
        </FieldLabel>
        <PlanSelect
          id={id}
          plans={plans.data}
          provider={bill.provider}
          value={picked}
          onChange={setPicked}
          disabled={update.isPending}
        />
        {update.error ? <BillEditError error={update.error} /> : null}
      </Field>
      <BillDialogFooter disabled={picked === plan || update.isPending} pending={update.isPending}>
        Save plan
      </BillDialogFooter>
    </form>
  );
}
