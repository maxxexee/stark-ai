import type { Bank } from "@stark/api/types";
import { Field, FieldLabel } from "@stark/ui/components/field";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@stark/ui/components/select";
import { useId } from "react";

export function BankSelect({
  banks,
  value,
  onChange,
}: {
  banks: Bank[];
  value: string;
  onChange: (code: string) => void;
}) {
  const id = useId();
  return (
    <Field className="gap-2.5">
      <FieldLabel htmlFor={id} className="font-normal text-fg-2">
        Bank
      </FieldLabel>
      <Select
        items={banks.map((bank) => ({ value: bank.code, label: bank.name }))}
        value={value || null}
        onValueChange={(code) => code && onChange(code)}
      >
        <SelectTrigger id={id} className="w-full">
          <SelectValue placeholder="Choose your bank" />
        </SelectTrigger>
        <SelectContent className="max-h-80">
          {banks.map((bank) => (
            <SelectItem key={bank.code} value={bank.code}>
              <span className="truncate">{bank.name}</span>
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </Field>
  );
}
