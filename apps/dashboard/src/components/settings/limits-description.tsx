import { FieldDescription } from "@stark/ui/components/field";
import { formatNaira } from "@stark/utils/format";

export function LimitsDescription({ spent }: { spent: number }) {
  return (
    <FieldDescription className="text-sm text-fg-2">
      Stark never pays more than this unless you approve it. Nobody, not even Stark, can raise these
      but you. You’ve spent {formatNaira(spent)} this month.
    </FieldDescription>
  );
}
