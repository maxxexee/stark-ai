import type { Receipt } from "@stark/api/types";
import { Empty, EmptyDescription } from "@stark/ui/components/empty";
import { RowList } from "@stark/ui/components/list-row";
import { ActivityRow } from "@/components/activity/activity-row";

export function MoneyMoves({ moves }: { moves: Receipt[] }) {
  return (
    <RowList>
      {moves.map((r) => (
        <ActivityRow key={r.id} receipt={r} />
      ))}
      {!moves.length ? (
        <Empty className="rounded-card border border-dashed border-border p-6">
          <EmptyDescription>No money in or out yet.</EmptyDescription>
        </Empty>
      ) : null}
    </RowList>
  );
}
