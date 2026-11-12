import { RadioGroup, RadioGroupItem } from "@stark/ui/components/radio-group";
import { cn } from "@stark/ui/utils/cn";
import type { ReactNode } from "react";

export function RadioList<T extends string>({
  label,
  value,
  onValueChange,
  children,
}: {
  label: string;
  value: T | undefined;
  onValueChange: (value: T) => void;
  children: ReactNode;
}) {
  return (
    <RadioGroup
      aria-label={label}
      value={value ?? null}
      onValueChange={(v) => onValueChange(v as T)}
      className="flex flex-col divide-y divide-border overflow-hidden rounded-card border border-border bg-card shadow-card"
    >
      {children}
    </RadioGroup>
  );
}

export function RadioRow({
  value,
  title,
  subtitle,
  disabled,
}: {
  value: string;
  title: ReactNode;
  subtitle?: ReactNode;
  disabled?: boolean;
}) {
  return (
    <label
      className={cn(
        "flex min-h-14 w-full cursor-pointer items-center gap-3 px-4 py-2.5 text-left transition-colors hover:bg-surface-2",
        "has-data-checked:bg-surface-selected",
        "has-data-disabled:cursor-not-allowed has-data-disabled:opacity-50",
      )}
    >
      <span className="flex flex-1 flex-col">
        <span className="font-medium">{title}</span>
        {subtitle ? <span className="text-sm text-muted-foreground">{subtitle}</span> : null}
      </span>
      <RadioGroupItem
        value={value}
        disabled={disabled}
        className="size-4.5 border-2 border-faint data-checked:border-[5px] data-checked:border-brand data-checked:bg-transparent dark:data-checked:bg-transparent [&_[data-slot=radio-group-indicator]]:hidden"
      />
    </label>
  );
}
