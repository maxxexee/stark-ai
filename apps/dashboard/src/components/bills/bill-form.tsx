import { useAddBill } from "@stark/api/mutations";
import { plansQuery } from "@stark/api/queries";
import type { Bill, BillKind } from "@stark/api/types";
import { Button } from "@stark/ui/components/button";
import { FieldGroup } from "@stark/ui/components/field";
import { Spinner } from "@stark/ui/components/spinner";
import { TextField } from "@stark/ui/components/text-field";
import { useQuery } from "@tanstack/react-query";
import { type ReactNode, type SubmitEvent, useState } from "react";
import { AddBillError } from "@/components/bills/add-bill-error";
import { BillKindChips } from "@/components/bills/bill-kind-chips";
import { PendingProviderNote } from "@/components/bills/pending-provider-note";
import { PlanField } from "@/components/bills/plan-field";
import { ProviderField } from "@/components/bills/provider-field";
import { BillKinds } from "@/lib/bills/bill-kinds";

export function BillForm({
  onAdded,
  submitLabel = "Add bill",
  footer,
}: {
  onAdded: (bill: Bill) => void;
  submitLabel?: string;
  footer?: ReactNode;
}) {
  const [kind, setKind] = useState<BillKind>("electricity");
  const [provider, setProvider] = useState(BillKinds.providers.electricity[0]!);
  const [reference, setReference] = useState("");
  const [label, setLabel] = useState(BillKinds.defaultNickname.electricity);
  const [plan, setPlan] = useState<string>();

  const addBill = useAddBill();

  const sellsPlans = kind === "data" || kind === "tv";
  const plans = useQuery({
    ...plansQuery(sellsPlans ? kind : undefined, provider),
    enabled: sellsPlans,
  });

  const handleKindChange = (next: BillKind) => {
    setKind(next);
    setProvider(BillKinds.providers[next][0]!);
    setLabel(BillKinds.defaultNickname[next]);
    setPlan(undefined);
    addBill.reset();
  };

  const handleProviderChange = (next: string) => {
    setProvider(next);
    setPlan(undefined);
  };

  const handleAddBill = (event: SubmitEvent<HTMLFormElement>) => {
    event.preventDefault();
    addBill.mutate(
      {
        kind,
        provider,
        reference: reference.replace(/\s+/g, ""),
        label: label.trim() || undefined,
        plan,
      },
      { onSuccess: onAdded },
    );
  };

  return (
    <form className="m-0" onSubmit={handleAddBill}>
      <FieldGroup className="gap-6">
        <BillKindChips kind={kind} onPick={handleKindChange} />

        <ProviderField kind={kind} provider={provider} onChange={handleProviderChange} />

        <TextField
          label={BillKinds.referenceLabel[kind]}
          inputMode="numeric"
          autoComplete="off"
          required
          value={reference}
          onChange={(e) => setReference(e.target.value)}
          className="[&_input]:tabular"
        />

        {sellsPlans ? (
          <PlanField plans={plans.data} provider={provider} value={plan} onChange={setPlan} />
        ) : null}

        <TextField label="Call it" value={label} onChange={(e) => setLabel(e.target.value)} />

        {kind === "internet" || kind === "water" ? <PendingProviderNote /> : null}

        {footer}

        {addBill.error ? <AddBillError error={addBill.error} /> : null}

        <Button
          type="submit"
          size="lg"
          block
          disabled={addBill.isPending || !reference.trim() || (sellsPlans && !plan)}
        >
          {addBill.isPending ? <Spinner /> : null}
          {addBill.isPending ? "Adding…" : submitLabel}
        </Button>
      </FieldGroup>
    </form>
  );
}
