import { Button } from "@stark/ui/components/button";
import {
  Empty,
  EmptyContent,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
} from "@stark/ui/components/empty";
import { Icons } from "@stark/ui/components/icons";
import { Link } from "@tanstack/react-router";

export function EmptyBills() {
  return (
    <Empty className="rounded-card border border-dashed border-border p-6">
      <EmptyHeader>
        <EmptyMedia variant="icon">
          <Icons.Bills size={16} />
        </EmptyMedia>
        <EmptyDescription>Add a bill and Stark starts watching it for you.</EmptyDescription>
      </EmptyHeader>
      <EmptyContent>
        <Button variant="secondary" nativeButton={false} render={<Link to="/bills/new" />}>
          <Icons.Add size={16} />
          Add your first bill
        </Button>
      </EmptyContent>
    </Empty>
  );
}
