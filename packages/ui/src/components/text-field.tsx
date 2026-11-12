import { Field, FieldDescription, FieldLabel } from "@stark/ui/components/field";
import { Input } from "@stark/ui/components/input";
import { type ComponentProps, useId } from "react";

export function TextField({
  label,
  hint,
  className,
  id,
  ...props
}: ComponentProps<typeof Input> & { label: string; hint?: string }) {
  const autoId = useId();
  const inputId = id ?? autoId;
  return (
    <Field className={className}>
      <FieldLabel htmlFor={inputId} className="text-sm font-medium text-fg-2">
        {label}
      </FieldLabel>
      <Input id={inputId} {...props} />
      {hint ? <FieldDescription className="text-sm">{hint}</FieldDescription> : null}
    </Field>
  );
}
