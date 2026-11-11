import { TooltipTrigger } from "@stark/ui/components/tooltip";
import { cn } from "@stark/ui/utils/cn";
import { Link } from "@tanstack/react-router";
import type { tabs } from "@/components/shell/tabs";
import { usePath } from "@/components/shell/use-path";
import { NavMatch } from "@/lib/navigation/nav-match";

export function DockTab({ tab: { to, label, icon: Icon, exact } }: { tab: (typeof tabs)[number] }) {
  const active = NavMatch.isActive(usePath(), to, exact);
  return (
    <TooltipTrigger
      content={label}
      render={
        <Link
          to={to}
          aria-label={label}
          aria-current={active ? "page" : undefined}
          className={cn(
            "flex size-10 items-center justify-center rounded-lg transition-colors",
            active
              ? "bg-brand-tint text-brand hover:text-brand"
              : "text-fg-2 hover:bg-surface-2 hover:text-fg",
          )}
        />
      }
    >
      <Icon size={18} />
    </TooltipTrigger>
  );
}
