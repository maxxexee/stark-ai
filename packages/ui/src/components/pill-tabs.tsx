import { Tabs, TabsList, TabsTrigger } from "@stark/ui/components/tabs";
import { cn } from "@stark/ui/utils/cn";
import type { ReactNode } from "react";

export type PillTab<T extends string> = { value: T; label: ReactNode };

/** Section filter (All / Electricity / ...): a segmented control on shadcn Tabs. */
export function PillTabs<T extends string>({
  tabs,
  value,
  onChange,
  label,
  className,
}: {
  tabs: PillTab<T>[];
  value: T;
  onChange: (value: T) => void;
  label: string;
  className?: string;
}) {
  return (
    <Tabs value={value} onValueChange={(v) => onChange(v as T)}>
      <TabsList
        aria-label={label}
        className={cn(
          "h-9 max-w-full justify-start gap-0.5 overflow-x-auto rounded-lg bg-muted p-0.5",
          className,
        )}
      >
        {tabs.map((tab) => (
          <TabsTrigger
            key={tab.value}
            value={tab.value}
            className={cn(pillTabClass(tab.value === value), "h-8 flex-none")}
          >
            {tab.label}
          </TabsTrigger>
        ))}
      </TabsList>
    </Tabs>
  );
}

/** One segment on its own, for links that act as section tabs. */
export function pillTabClass(active: boolean) {
  return cn(
    "inline-flex h-8 cursor-pointer items-center rounded-lg border-0 px-3 text-sm font-medium no-underline",
    active
      ? "bg-card text-foreground shadow-sm data-active:bg-card data-active:text-foreground"
      : "bg-transparent text-muted-foreground hover:text-foreground",
  );
}
