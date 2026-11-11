import type { Receipt } from "@stark/api/types";
import { cn } from "@stark/ui/utils/cn";
import { formatDateTime, formatNaira } from "@stark/utils/format";
import { Receipts } from "@/lib/receipts/receipts";

export function ReceiptAmount({ receipt }: { receipt: Receipt }) {
  return (
    <div className="flex flex-col gap-1">
      <span
        className={cn(
          "tabular text-3xl font-semibold tracking-tight",
          receipt.status === "declined" && "text-muted-foreground",
        )}
      >
        {formatNaira(Receipts.signedAmount(receipt), {
          sign: receipt.type === "deposit",
        })}
      </span>
      <span className="text-sm text-muted-foreground">
        {receipt.bill_label} · {formatDateTime(receipt.created_at)}
      </span>
    </div>
  );
}
