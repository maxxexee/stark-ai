import { cn } from "@stark/ui/utils/cn";
import type { ReactNode } from "react";

export function SectionHeading({
  children,
  action,
  className,
}: {
  children: ReactNode;
  action?: ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("flex min-h-8 items-center gap-3", className)}>
      <h2 className="m-0 text-base font-semibold text-foreground">{children}</h2>
      {action ? <span className="ml-auto text-sm text-muted-foreground">{action}</span> : null}
    </div>
  );
}
