import { Button } from "@stark/ui/components/button";
import { Empty, EmptyDescription } from "@stark/ui/components/empty";
import { Icons } from "@stark/ui/components/icons";
import { Link } from "@tanstack/react-router";

export function BillsEmpty() {
  return (
    <Empty className="rounded-card border border-dashed border-border p-6">
      <EmptyDescription>No bills here yet.</EmptyDescription>
      <Button variant="secondary" nativeButton={false} render={<Link to="/bills/new" />}>
        <Icons.Add size={16} />
        Add a bill
      </Button>
    </Empty>
  );
}
