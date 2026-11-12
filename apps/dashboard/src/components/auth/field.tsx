import type { ReactNode } from "react";

export function Field({
  label,
  type = "text",
  autoComplete,
  placeholder,
  trailing,
  value,
  onChange,
  required,
}: {
  label: string;
  type?: string;
  autoComplete?: string;
  placeholder?: string;
  trailing?: ReactNode;
  value: string;
  onChange: (value: string) => void;
  required?: boolean;
}) {
  return (
    <label className="flex flex-col gap-1.5">
      <span className="text-sm font-medium text-fg-2">{label}</span>
      <span className="flex h-10 items-center gap-1 rounded-lg border border-input bg-card pr-1 pl-3 shadow-control transition-colors focus-within:border-ring focus-within:ring-3 focus-within:ring-ring/25">
        <input
          type={type}
          autoComplete={autoComplete}
          placeholder={placeholder}
          required={required}
          value={value}
          onChange={(event) => onChange(event.target.value)}
          className="h-full w-full min-w-0 bg-transparent text-base text-fg outline-none placeholder:text-faint"
        />
        {trailing}
      </span>
    </label>
  );
}
