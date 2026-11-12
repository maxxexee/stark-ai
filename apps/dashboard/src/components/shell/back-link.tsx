import { Icons } from "@stark/ui/components/icons";
import { Link } from "@tanstack/react-router";
import type { ReactNode } from "react";

// A plain link, not a padded button, so its chevron lines up with the title below it.
export function BackLink({ to, children }: { to: string; children: ReactNode }) {
  return (
    <Link
      to={to}
      className="-mb-4 -ml-1 inline-flex h-6 items-center gap-0.5 self-start text-sm text-muted-foreground no-underline hover:text-fg"
    >
      <Icons.ChevronLeft size={16} />
      {children}
    </Link>
  );
}
