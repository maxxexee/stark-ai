import type { Bill } from "@stark/api/types";
import { pillTabClass } from "@stark/ui/components/pill-tabs";
import { Link } from "@tanstack/react-router";

export function BillSectionsNav({ bill }: { bill: Bill }) {
  return (
    <nav
      aria-label="Sections"
      className="flex h-9 w-fit max-w-full gap-0.5 overflow-x-auto rounded-lg bg-muted p-0.5"
    >
      <span aria-current="page" className={pillTabClass(true)}>
        Overview
      </span>
      <Link to="/activity" search={{ bill: bill.id }} className={pillTabClass(false)}>
        History
      </Link>
      <Link to="/settings" className={pillTabClass(false)}>
        Limits
      </Link>
    </nav>
  );
}
