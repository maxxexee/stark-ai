import { ChipGroup, ChoiceChip } from "@stark/ui/components/choice-chip";
import { Field, FieldError, FieldLabel } from "@stark/ui/components/field";
import { cn } from "@stark/ui/utils/cn";
import { formatAmountInput, parseAmountInput } from "@stark/utils/format";
import { type ReactNode, useId } from "react";

/**
 * Every amount, cap and threshold in Stark is set this way: there are no sliders anywhere in the
 * product.
 */
export function AmountField({
  label,
  value,
  onChange,
  presets,
  error,
  className,
}: {
  label: string;
  value: number;
  onChange: (value: number) => void;
  presets?: number[];
  error?: ReactNode;
  className?: string;
}) {
  const id = useId();
  return (
    <Field data-invalid={error ? true : undefined} className={cn("gap-2", className)}>
      <div className="rounded-card bg-muted p-1">
        <div className="flex flex-col gap-3 rounded-lg bg-card px-4 py-3.5">
          <FieldLabel htmlFor={id} className="text-sm font-normal text-muted-foreground">
            {label}
          </FieldLabel>
          <div className="flex h-10 items-center gap-3">
            <input
              id={id}
              inputMode="numeric"
              autoComplete="off"
              aria-invalid={error ? true : undefined}
              value={formatAmountInput(value)}
              onChange={(e) => onChange(parseAmountInput(e.target.value))}
              className="tabular h-full min-w-0 flex-1 bg-transparent p-0 text-3xl font-normal tracking-tight text-foreground outline-none"
            />
            <span className="flex h-9 shrink-0 items-center rounded-lg bg-muted px-3 text-base font-medium">
              NGN
            </span>
          </div>
        </div>
      </div>
      {presets?.length ? (
        <ChipGroup label={`Quick amounts for ${label.toLowerCase()}`}>
          {presets.map((p) => (
            <ChoiceChip key={p} size="sm" selected={p === value} onClick={() => onChange(p)}>
              ₦{formatAmountInput(p)}
            </ChoiceChip>
          ))}
        </ChipGroup>
      ) : null}
      <FieldError>{error}</FieldError>
    </Field>
  );
}
