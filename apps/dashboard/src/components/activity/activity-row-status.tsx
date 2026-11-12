import { cn } from "@stark/ui/utils/cn";
import type { StatusDisplay } from "@/lib/receipts/receipts";

export function ActivityRowStatus({ status }: { status: StatusDisplay }) {
  return (
    <span
      className={cn(
        "min-w-18 text-right text-sm",
        status.tone === "brand" && "text-brand",
        status.tone === "muted" && "text-muted-foreground",
        status.tone === "fg" && "text-fg",
      )}
    >
      {status.label}
    </span>
  );
}
