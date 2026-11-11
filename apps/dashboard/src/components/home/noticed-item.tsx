import type { Suggestion } from "@stark/api/types";
import { cn } from "@stark/ui/utils/cn";

export function NoticedItem({ suggestion }: { suggestion: Suggestion }) {
  return (
    <div className="flex items-start gap-2">
      <span
        aria-hidden="true"
        className={cn(
          "mt-[7px] size-1.5 shrink-0 rounded-full",
          suggestion.severity === "alert"
            ? "bg-destructive"
            : suggestion.severity === "warn"
              ? "bg-brand"
              : "bg-faint",
        )}
      />
      <span className="text-base">{suggestion.text}</span>
    </div>
  );
}
