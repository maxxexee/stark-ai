import type { BillKind } from "@stark/api/types";
import { Field, FieldLabel } from "@stark/ui/components/field";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@stark/ui/components/select";
import { useId } from "react";
import { BillKinds } from "@/lib/bills/bill-kinds";

export function ProviderField({
  kind,
  provider,
  onChange,
}: {
  kind: BillKind;
  provider: string;
  onChange: (provider: string) => void;
}) {
  const providerId = useId();

  const handleProviderChange = (next: string | null) => {
    if (next === null) return;
    onChange(next);
  };

  return (
    <Field>
      <FieldLabel htmlFor={providerId} className="text-sm font-medium text-fg-2">
        Provider
      </FieldLabel>
      <Select value={provider} onValueChange={handleProviderChange}>
        <SelectTrigger id={providerId} className="w-full">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {BillKinds.providers[kind].map((p) => (
            <SelectItem key={p} value={p}>
              {p}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </Field>
  );
}
