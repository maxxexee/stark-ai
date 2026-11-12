import { Toggle } from "@stark/ui/components/toggle";
import { cn } from "@stark/ui/utils/cn";
import type { ComponentProps } from "react";

type ChoiceChipProps = Omit<ComponentProps<typeof Toggle>, "pressed" | "size"> & {
  selected: boolean;
  size?: "sm" | "lg";
};

export function ChoiceChip({ selected, size = "lg", className, ...props }: ChoiceChipProps) {
  return (
    <Toggle
      pressed={selected}
      className={cn(
        "cursor-pointer rounded-lg border border-border bg-card font-medium text-foreground shadow-control hover:bg-muted",
        size === "lg" ? "h-10 text-base" : "h-8 px-3 text-sm",
        "aria-pressed:border-brand-line aria-pressed:bg-brand-wash aria-pressed:text-brand aria-pressed:hover:bg-brand-tint",
        className,
      )}
      {...props}
    />
  );
}

export function ChipGroup({
  label,
  className,
  children,
  columns,
}: {
  label: string;
  className?: string;
  children: React.ReactNode;
  columns?: number;
}) {
  return (
    <div
      role="group"
      aria-label={label}
      className={cn(columns ? "grid gap-2" : "flex flex-wrap gap-2", className)}
      style={columns ? { gridTemplateColumns: `repeat(${columns}, minmax(0, 1fr))` } : undefined}
    >
      {children}
    </div>
  );
}
