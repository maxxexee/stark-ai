import type { PaymentRequest } from "@stark/api/types";
import { formatNaira } from "@stark/utils/format";
import { Approvals } from "@/lib/approvals/approvals";

export function ApprovalSummary({ request }: { request: PaymentRequest }) {
  return (
    <>
      <div className="flex flex-col gap-1">
        <span className="text-sm text-fg-2">Stark wants to pay</span>
        <span className="tabular text-3xl font-semibold tracking-tight">
          {formatNaira(request.amount_ngn)}
        </span>
        <span className="text-base">to {request.bill_label}</span>
      </div>
      <p className="m-0 text-sm text-fg-2">
        {Approvals.reason(request)}, so it asked first. Approving pays this one amount. Your limits
        stay the same. {Approvals.timeLeft(request)}.
      </p>
    </>
  );
}
