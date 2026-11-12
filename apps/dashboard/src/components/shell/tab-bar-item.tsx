import { cn } from "@stark/ui/utils/cn";
import { Link } from "@tanstack/react-router";
import type { tabs } from "@/components/shell/tabs";
import { usePath } from "@/components/shell/use-path";
import { NavMatch } from "@/lib/navigation/nav-match";

export function TabBarItem({
  tab: { to, label, icon: Icon, exact },
}: {
  tab: (typeof tabs)[number];
}) {
  const active = NavMatch.isActive(usePath(), to, exact);
  return (
    <Link
      to={to}
      aria-current={active ? "page" : undefined}
      className={cn(
        "flex h-12 flex-1 flex-col items-center justify-center gap-0.5 text-xs font-medium no-underline",
        active ? "text-brand hover:text-brand" : "text-idle hover:text-fg",
      )}
    >
      <Icon size={22} />
      {label}
    </Link>
  );
}
