import type { Receipt } from "@stark/api/types";
import { cn } from "@stark/ui/utils/cn";
import { formatNaira } from "@stark/utils/format";

export function TopUpBar({
  receipt,
  max,
  latest,
  label,
}: {
  receipt: Receipt;
  max: number;
  latest: boolean;
  label: string;
}) {
  return (
    <div className="flex min-w-0 flex-1 flex-col items-center gap-2">
      <div className="flex h-36 w-full flex-col items-center justify-end gap-1 border-b border-border">
        <span className="tabular text-xs text-muted-foreground">
          {formatNaira(receipt.amount_ngn)}
        </span>
        <span
          className={cn("w-full max-w-12 rounded-t-md", latest ? "bg-brand" : "bg-track")}
          style={{ height: `${Math.max(6, (receipt.amount_ngn / max) * 80)}%` }}
        />
      </div>
      <span className="tabular text-xs text-muted-foreground">{label}</span>
    </div>
  );
}
