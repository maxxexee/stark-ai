import { CopyButton } from "@stark/ui/components/copy-button";
import { formatToken } from "@stark/utils/format";
import { PaymentMode } from "@/lib/receipts/payment-mode";

export function TokenLine({ token, note }: { token: string; note?: string }) {
  return (
    <div className="flex flex-wrap items-center gap-3 px-4 py-3">
      <span className="flex min-w-0 flex-[1_1_0] flex-col">
        <span className="tabular text-base font-medium whitespace-nowrap sm:text-lg">
          {formatToken(token)}
        </span>
        <span className="text-sm text-muted-foreground">
          {[note, PaymentMode.live ? null : "sample token"].filter(Boolean).join(" · ")}
        </span>
      </span>
      <CopyButton value={token.replace(/\s+/g, "")} />
    </div>
  );
}
