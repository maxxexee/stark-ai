import { Empty, EmptyDescription } from "@stark/ui/components/empty";

export function ApprovalsEmpty() {
  return (
    <Empty className="rounded-card border border-dashed border-border p-6">
      <EmptyDescription>Nothing is waiting on you.</EmptyDescription>
    </Empty>
  );
}
