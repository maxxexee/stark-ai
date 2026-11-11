import { cn } from "@stark/ui/utils/cn";
import type { HTMLAttributes } from "react";

/** The small grey label above a number. Sentence case, never shouted. */
export function Eyebrow({ className, ...props }: HTMLAttributes<HTMLSpanElement>) {
  return <span className={cn("text-xs font-medium text-muted-foreground", className)} {...props} />;
}
