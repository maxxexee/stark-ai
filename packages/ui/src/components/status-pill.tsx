import { Badge } from "@stark/ui/components/badge";
import { cn } from "@stark/ui/utils/cn";
import type { ReactNode } from "react";

/** A small status badge with a dot, e.g. "Running low". */
export function StatusPill({
  children,
  tone = "brand",
  className,
}: {
  children: ReactNode;
  tone?: "brand" | "muted";
  className?: string;
}) {
  return (
    <Badge
      variant="secondary"
      className={cn(
        "h-5 gap-1.5 rounded-lg bg-muted px-1.5 text-xs font-medium",
        tone === "brand" ? "text-brand" : "text-muted-foreground",
        className,
      )}
    >
      <span
        aria-hidden="true"
        className={cn("size-1.5 rounded-full", tone === "brand" ? "bg-brand" : "bg-idle")}
      />
      {children}
    </Badge>
  );
}
