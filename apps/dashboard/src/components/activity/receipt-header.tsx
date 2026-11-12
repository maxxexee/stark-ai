import { SheetTitle } from "@stark/ui/components/sheet";
import { StatusPill } from "@stark/ui/components/status-pill";
import type { StatusDisplay } from "@/lib/receipts/receipts";

export function ReceiptHeader({ status }: { status: StatusDisplay }) {
  return (
    <div className="flex items-center gap-3 pr-10">
      <SheetTitle>Receipt</SheetTitle>
      <StatusPill tone={status.tone === "brand" ? "brand" : "muted"}>{status.label}</StatusPill>
    </div>
  );
}
