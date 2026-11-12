import type { Receipt } from "@stark/api/types";
import { Sheet, SheetContent } from "@stark/ui/components/sheet";
import { useIsMobile } from "@stark/ui/hooks/use-mobile";
import { useRef } from "react";
import { ReceiptAmount } from "@/components/activity/receipt-amount";
import { ReceiptHeader } from "@/components/activity/receipt-header";
import { ReceiptNote } from "@/components/activity/receipt-note";
import { ReceiptStats } from "@/components/activity/receipt-stats";
import { TokenLine } from "@/components/pay/token-line";
import { Receipts } from "@/lib/receipts/receipts";

/** Opens while `receipt` is set; a bottom sheet on phones, a side panel wider up. */
export function ReceiptSheet({
  receipt,
  onClose,
}: {
  receipt: Receipt | undefined;
  onClose: () => void;
}) {
  const isMobile = useIsMobile();
  // Keeps the last receipt on screen while the sheet animates closed.
  const last = useRef(receipt);
  if (receipt) last.current = receipt;
  const shown = receipt ?? last.current;

  return (
    <Sheet open={Boolean(receipt)} onOpenChange={(open) => open || onClose()}>
      {shown ? (
        <SheetContent
          side={isMobile ? "bottom" : "right"}
          className="gap-6 p-5 data-[side=bottom]:rounded-t-2xl"
        >
          <ReceiptHeader status={Receipts.status(shown)} />
          <ReceiptAmount receipt={shown} />
          <ReceiptNote status={shown.status} />
          {shown.token && shown.status === "delivered" ? <TokenLine token={shown.token} /> : null}
          <ReceiptStats receipt={shown} />
        </SheetContent>
      ) : null}
    </Sheet>
  );
}
