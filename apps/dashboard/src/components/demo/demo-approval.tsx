import type { PaymentRequest } from "@stark/api/types";
import { Card } from "@stark/ui/components/card";
import { ApprovalSummary } from "@/components/approvals/approval-summary";

export function DemoApproval({ request }: { request: PaymentRequest }) {
  return (
    <Card className="gap-3 border-brand-line">
      <ApprovalSummary request={request} />
      <p className="m-0 text-sm text-fg-2">
        In your own account, you approve or decline it right here. A voice note or a chat can ask,
        but only this app can say yes.
      </p>
    </Card>
  );
}
