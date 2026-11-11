import { errorCopy } from "@stark/api/errors";
import { useDecideRequest } from "@stark/api/mutations";
import type { PaymentRequest } from "@stark/api/types";
import { Button } from "@stark/ui/components/button";
import { Card } from "@stark/ui/components/card";
import { formatNaira } from "@stark/utils/format";
import { ApprovalSummary } from "@/components/approvals/approval-summary";
import { FormError } from "@/components/auth/form-error";

export function ApprovalCard({ request }: { request: PaymentRequest }) {
  const decide = useDecideRequest();

  const handleApprove = () => decide.mutate({ id: request.id, approve: true });
  const handleDecline = () => decide.mutate({ id: request.id, approve: false });

  return (
    <Card className="gap-4 border-brand-line">
      <ApprovalSummary request={request} />
      <div className="flex flex-wrap gap-2">
        <Button variant="brand" onClick={handleApprove} disabled={decide.isPending}>
          Approve {formatNaira(request.amount_ngn)}
        </Button>
        <Button variant="secondary" onClick={handleDecline} disabled={decide.isPending}>
          Decline
        </Button>
      </div>
      <FormError message={decide.isError ? errorCopy(decide.error) : null} />
    </Card>
  );
}
