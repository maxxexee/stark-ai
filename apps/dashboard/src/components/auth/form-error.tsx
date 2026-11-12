import { cn } from "@stark/ui/utils/cn";

export function FormError({ message, className }: { message: string | null; className?: string }) {
  if (!message) return null;

  return (
    <p role="alert" className={cn("m-0 text-sm text-destructive", className)}>
      {message}
    </p>
  );
}
