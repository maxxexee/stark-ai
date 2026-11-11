import type { Receipt } from "@stark/api/types";
import { cn } from "@stark/ui/utils/cn";
import { formatNaira } from "@stark/utils/format";

export function TopUpBar({
  receipt,
  max,
  latest,
}: {
  receipt: Receipt;
  max: number;
  latest: boolean;
}) {
  return (
    <div className="flex h-full flex-1 flex-col items-center justify-end gap-1">
      <span className="tabular text-xs text-muted-foreground">
        {formatNaira(receipt.amount_ngn)}
      </span>
      <span
        className={cn("w-full max-w-9 rounded-lg", latest ? "bg-brand" : "bg-track")}
        style={{ height: `${Math.max(8, (receipt.amount_ngn / max) * 80)}%` }}
      />
    </div>
  );
}
