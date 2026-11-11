import { Empty, EmptyDescription } from "@stark/ui/components/empty";

export function ActivityEmpty() {
  return (
    <Empty className="rounded-card border border-dashed border-border p-6">
      <EmptyDescription>Nothing here yet.</EmptyDescription>
    </Empty>
  );
}
