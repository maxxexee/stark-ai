import type { PaymentRequest } from "@stark/api/types";
import { ListRow, RowText } from "@stark/ui/components/list-row";
import { formatActivityTime, formatNaira } from "@stark/utils/format";
import { Approvals } from "@/lib/approvals/approvals";

export function ApprovalHistoryRow({ request }: { request: PaymentRequest }) {
  return (
    <ListRow>
      <RowText
        title={`${formatNaira(request.amount_ngn)} to ${request.bill_label}`}
        subtitle={`${Approvals.reason(request)} · ${formatActivityTime(request.created_at)}`}
      />
      <span className="text-sm text-muted-foreground">{Approvals.outcome(request)}</span>
    </ListRow>
  );
}
