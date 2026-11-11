import { cn } from "@stark/ui/utils/cn";
import type { ReactNode } from "react";

/** A highlighted strip for something that needs the user (low meter, a refused payment). */
export function Notice({
  icon,
  title,
  children,
  actions,
  tone = "brand",
  className,
}: {
  icon?: ReactNode;
  title: ReactNode;
  children?: ReactNode;
  actions?: ReactNode;
  tone?: "brand" | "muted";
  className?: string;
}) {
  return (
    <section
      className={cn(
        "flex flex-wrap items-center gap-3 rounded-card border px-4 py-3",
        tone === "brand" ? "border-brand-line bg-brand-wash" : "border-border bg-card",
        className,
      )}
    >
      {icon ? (
        <span className="flex size-5 flex-none items-center justify-center text-brand">{icon}</span>
      ) : null}
      <span className="flex flex-[1_1_240px] flex-col gap-0.5">
        <span className="font-medium">{title}</span>
        {children ? <span className="text-sm text-fg-2">{children}</span> : null}
      </span>
      {actions}
    </section>
  );
}
