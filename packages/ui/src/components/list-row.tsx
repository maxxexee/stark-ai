import { cn } from "@stark/ui/utils/cn";
import type { HTMLAttributes, ReactNode } from "react";

export const listRowClass =
  "flex min-h-14 flex-wrap items-center gap-3 px-4 py-2.5 text-fg no-underline transition-colors hover:bg-surface-2";

/** A row's title and grey subtitle. Grows to fill the row. */
export function RowText({
  title,
  subtitle,
  className,
}: {
  title: ReactNode;
  subtitle?: ReactNode;
  className?: string;
}) {
  return (
    <span className={cn("flex min-w-0 flex-[1_1_0] flex-col sm:flex-[1_1_180px]", className)}>
      <span className="truncate font-medium">{title}</span>
      {subtitle ? <span className="truncate text-sm text-muted-foreground">{subtitle}</span> : null}
    </span>
  );
}

export function ListRow({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return <div className={cn(listRowClass, className)} {...props} />;
}

/** Rows grouped in one card, split by hairlines. */
export function RowList({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn(
        "flex flex-col divide-y divide-border overflow-hidden rounded-card border border-border bg-card shadow-card",
        className,
      )}
      {...props}
    />
  );
}
