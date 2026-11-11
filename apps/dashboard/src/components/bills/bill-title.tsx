import type { Bill } from "@stark/api/types";
import { StatusPill } from "@stark/ui/components/status-pill";
import { BillIcon } from "@/components/bills/bill-icon";

export function BillTitle({ bill, attention }: { bill: Bill; attention: boolean }) {
  return (
    <div className="flex flex-wrap items-center gap-3">
      <BillIcon bill={bill} />
      <h1 className="m-0 text-2xl font-semibold tracking-tight">{bill.label}</h1>
      <StatusPill tone={attention ? "brand" : "muted"}>
        {attention ? "Running low" : "All good"}
      </StatusPill>
    </div>
  );
}
