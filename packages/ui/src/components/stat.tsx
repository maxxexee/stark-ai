import { Eyebrow } from "@stark/ui/components/eyebrow";
import { cn } from "@stark/ui/utils/cn";
import type { ReactNode } from "react";

export function StatGrid({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <div
      className={cn(
        "grid grid-cols-[repeat(auto-fit,minmax(140px,1fr))] gap-x-6 gap-y-4",
        className,
      )}
    >
      {children}
    </div>
  );
}

export function Stat({ label, children }: { label: ReactNode; children: ReactNode }) {
  return (
    <div className="flex min-w-0 flex-col gap-1">
      <Eyebrow>{label}</Eyebrow>
      <span className="tabular text-base font-medium text-fg">{children}</span>
    </div>
  );
}
