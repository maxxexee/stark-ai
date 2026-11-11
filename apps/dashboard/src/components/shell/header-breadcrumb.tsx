import { LogoMark } from "@stark/ui/components/logo";
import { Link } from "@tanstack/react-router";
import { usePath } from "@/components/shell/use-path";
import { NavMatch } from "@/lib/navigation/nav-match";

const pageNames: [string, string][] = [
  ["/bills", "Bills"],
  ["/connect", "Connect a chat"],
  ["/pay", "Pay a bill"],
  ["/activity", "Activity"],
  ["/approvals", "Approvals"],
  ["/wallet", "Wallet"],
  ["/settings", "Settings"],
];

export function HeaderBreadcrumb() {
  const path = usePath();
  const page = pageNames.find(([p]) => NavMatch.isActive(path, p, false))?.[1] ?? "Home";
  return (
    <nav aria-label="Breadcrumb" className="flex items-center gap-2.5">
      <Link
        to="/"
        aria-label="Stark home"
        className="flex items-center gap-2.5 text-fg no-underline hover:text-fg"
      >
        <LogoMark size={20} cutout="#ffffff" />
        <span className="text-base font-semibold">Stark</span>
      </Link>
      <span aria-hidden="true" className="hidden text-faint sm:inline">
        /
      </span>
      <span aria-current="page" className="hidden text-base text-fg-2 sm:inline">
        {page}
      </span>
    </nav>
  );
}
