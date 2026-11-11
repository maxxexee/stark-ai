import { cn } from "@stark/ui/utils/cn";
import type { ReactNode } from "react";

/** The neutral rounded square that holds a bill or method icon. */
export function IconTile({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <span
      aria-hidden="true"
      className={cn(
        "flex size-8 flex-none items-center justify-center rounded-lg bg-muted text-fg-2",
        className,
      )}
    >
      {children}
    </span>
  );
}
