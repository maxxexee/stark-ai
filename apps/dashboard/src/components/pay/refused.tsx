import { errorCopy, isApiError } from "@stark/api/errors";
import { limitsQuery } from "@stark/api/queries";
import { Button } from "@stark/ui/components/button";
import { Icons } from "@stark/ui/components/icons";
import { Notice } from "@stark/ui/components/notice";
import { formatNaira } from "@stark/utils/format";
import { useSuspenseQuery } from "@tanstack/react-query";

export function Refused({ error, onPay }: { error: Error; onPay: (amount: number) => void }) {
  const { data: limits } = useSuspenseQuery(limitsQuery());
  const offer = isApiError(error, "over_per_payment_cap")
    ? limits.per_payment_cap_ngn
    : isApiError(error, "over_cap")
      ? limits.remaining_cap_ngn
      : null;
  return (
    <div role="alert">
      <Notice
        icon={<Icons.Warning size={16} />}
        title={errorCopy(error)}
        actions={
          offer ? (
            <Button variant="secondary" onClick={() => onPay(offer)}>
              Pay {formatNaira(offer)} instead
            </Button>
          ) : null
        }
      />
    </div>
  );
}
