import type { BillKind } from "@stark/api/types";
import { ChipGroup, ChoiceChip } from "@stark/ui/components/choice-chip";
import { BillKinds } from "@/lib/bills/bill-kinds";

export function BillKindChips({
  kind,
  onPick,
}: {
  kind: BillKind;
  onPick: (kind: BillKind) => void;
}) {
  return (
    <ChipGroup label="Bill type" columns={3}>
      {BillKinds.all.map((k) => (
        <ChoiceChip key={k.kind} selected={k.kind === kind} onClick={() => onPick(k.kind)}>
          {k.label}
        </ChoiceChip>
      ))}
    </ChipGroup>
  );
}
