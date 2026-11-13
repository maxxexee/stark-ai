import { Button } from "@stark/ui/components/button";
import { TextField } from "@stark/ui/components/text-field";
import type { OperatorLimit } from "@/lib/admin/admin-api";

const WHOLE = new Intl.NumberFormat("en-NG");

/**
 * One limit: its value to edit, shown with commas (`text` itself stays plain digits, so the
 * parent's parsing never sees them), its default while overridden, and a way back to it.
 */
export function AdminLimitField({
  limit,
  text,
  invalid,
  disabled,
  onChange,
  onReset,
}: {
  limit: OperatorLimit;
  text: string;
  invalid: boolean;
  disabled: boolean;
  onChange: (text: string) => void;
  onReset: () => void;
}) {
  let hint: string | undefined;
  if (invalid) {
    hint = `A whole number from ${WHOLE.format(limit.minimum)} to ${WHOLE.format(limit.maximum)}`;
  } else if (limit.overridden) {
    hint = `Default ${WHOLE.format(limit.default)}`;
  }

  return (
    <div className="flex flex-col items-start gap-1">
      <TextField
        className="w-full"
        label={limit.unit === "count" ? limit.label : `${limit.label} (${limit.unit})`}
        hint={hint}
        inputMode="numeric"
        aria-invalid={invalid}
        value={/^\d+$/.test(text) ? WHOLE.format(Number(text)) : text}
        onChange={(event) => onChange(event.target.value.replace(/[,\s]/g, ""))}
      />
      {limit.overridden ? (
        <Button variant="ghost" size="sm" onClick={onReset} disabled={disabled}>
          Use default
        </Button>
      ) : null}
    </div>
  );
}
