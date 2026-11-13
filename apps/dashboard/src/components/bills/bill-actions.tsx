import type { Bill } from "@stark/api/types";
import { Button } from "@stark/ui/components/button";
import { Link } from "@tanstack/react-router";
import { type BillEdit, BillEditMenu } from "@/components/bills/bill-edit-menu";
import { Bills } from "@/lib/bills/bills";

export function BillActions({ bill, onEdit }: { bill: Bill; onEdit: (edit: BillEdit) => void }) {
  return (
    <div className="flex flex-wrap gap-2">
      {Bills.isPayable(bill) ? (
        <Button nativeButton={false} render={<Link to="/pay" search={{ bill: bill.id }} />}>
          {bill.plan_price_ngn ? "Renew" : "Top up"}
        </Button>
      ) : null}
      <BillEditMenu bill={bill} onEdit={onEdit} />
    </div>
  );
}
