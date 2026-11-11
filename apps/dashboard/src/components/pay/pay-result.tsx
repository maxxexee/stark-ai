import type { Bill, Receipt } from "@stark/api/types";
import { Card } from "@stark/ui/components/card";
import { IconTile } from "@stark/ui/components/icon-tile";
import { Icons } from "@stark/ui/components/icons";
import { PayResultActions } from "@/components/pay/pay-result-actions";
import { TokenLine } from "@/components/pay/token-line";

export function PayResult({
  receipt,
  bill,
  onAgain,
}: {
  receipt: Receipt;
  bill?: Bill;
  onAgain: () => void;
}) {
  const delivered = receipt.status === "delivered";
  const title = delivered
    ? receipt.token
      ? "Paid. Here’s your token."
      : `Paid. ${bill?.label ?? "Your bill"} is topped up.`
    : receipt.status === "pending"
      ? "Still going through"
      : "That didn’t go through";
  const body = delivered
    ? receipt.token
      ? "Type it into your meter keypad."
      : null
    : receipt.status === "pending"
      ? "The provider is still processing it. You haven’t been charged yet, and Stark won’t buy twice."
      : "The provider refused it. Nothing was charged.";

  return (
    <Card aria-live="polite">
      <div className="flex items-center gap-3">
        <IconTile>{delivered ? <Icons.Check size={16} /> : <Icons.Clock size={16} />}</IconTile>
        <span className="text-lg font-semibold">{title}</span>
      </div>
      {receipt.token ? <TokenLine token={receipt.token} /> : null}
      {body ? <span className="text-sm text-muted-foreground">{body}</span> : null}
      <PayResultActions onAgain={onAgain} />
    </Card>
  );
}
