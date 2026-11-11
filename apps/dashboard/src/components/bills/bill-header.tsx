import type { Bill } from "@stark/api/types";
import { BillFacts } from "@/components/bills/bill-facts";
import { BillTitle } from "@/components/bills/bill-title";

export function BillHeader({
  bill,
  attention,
  firstPaid,
}: {
  bill: Bill;
  attention: boolean;
  firstPaid: string | undefined;
}) {
  return (
    <div className="flex flex-col gap-2">
      <BillTitle bill={bill} attention={attention} />
      <BillFacts bill={bill} firstPaid={firstPaid} />
    </div>
  );
}
