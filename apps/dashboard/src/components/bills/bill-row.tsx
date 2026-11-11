import type { Bill, State } from "@stark/api/types";
import { Icons } from "@stark/ui/components/icons";
import { listRowClass, RowText } from "@stark/ui/components/list-row";
import { cn } from "@stark/ui/utils/cn";
import { Link } from "@tanstack/react-router";
import { BillIcon } from "@/components/bills/bill-icon";
import { Bills } from "@/lib/bills/bills";

export function BillRow({ bill, state }: { bill: Bill; state: State }) {
  const status = Bills.status(bill, state);
  return (
    <Link to="/bills/$billId" params={{ billId: bill.id }} className={listRowClass}>
      <BillIcon bill={bill} />
      <RowText title={bill.label} subtitle={Bills.subtitle(bill)} />
      <span className={cn("text-sm", status.attention ? "text-brand" : "text-muted-foreground")}>
        {status.text}
      </span>
      <Icons.ChevronRight size={16} className="text-muted-foreground" />
    </Link>
  );
}
