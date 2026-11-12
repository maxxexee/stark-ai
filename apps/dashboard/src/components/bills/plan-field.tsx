import type { Plan } from "@stark/api/types";
import { Field, FieldLabel } from "@stark/ui/components/field";
import { useId } from "react";
import { PlanSelect } from "@/components/bills/plan-select";

export function PlanField({
  plans,
  provider,
  value,
  onChange,
}: {
  plans: Plan[] | undefined;
  provider: string;
  value: string | undefined;
  onChange: (plan: string) => void;
}) {
  const planId = useId();
  return (
    <Field>
      <FieldLabel htmlFor={planId} className="text-sm font-medium text-fg-2">
        Plan
      </FieldLabel>
      <PlanSelect id={planId} plans={plans} provider={provider} value={value} onChange={onChange} />
    </Field>
  );
}
