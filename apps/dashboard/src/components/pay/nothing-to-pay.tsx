import { Button } from "@stark/ui/components/button";
import {
  Empty,
  EmptyContent,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from "@stark/ui/components/empty";
import { Icons } from "@stark/ui/components/icons";
import { Link } from "@tanstack/react-router";

export function NothingToPay() {
  return (
    <Empty className="rounded-card border border-dashed border-border">
      <EmptyHeader>
        <EmptyMedia variant="icon">
          <Icons.Bills size={16} />
        </EmptyMedia>
        <EmptyTitle>Nothing to pay yet</EmptyTitle>
        <EmptyDescription>Add a bill first, then Stark can pay it.</EmptyDescription>
      </EmptyHeader>
      <EmptyContent>
        <Button nativeButton={false} render={<Link to="/bills/new" />}>
          Add a bill
        </Button>
      </EmptyContent>
    </Empty>
  );
}
