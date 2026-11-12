import { Button } from "@stark/ui/components/button";
import type { ReactNode } from "react";
import { MethodIcon } from "@/components/auth/method-icon";
import type { Method } from "@/components/auth/methods";

export function SignInOption({
  method,
  tag,
  disabled,
  onClick,
  children,
}: {
  method: Method;
  tag?: string;
  disabled?: boolean;
  onClick?: () => void;
  children: ReactNode;
}) {
  return (
    <Button
      type="button"
      variant="outline"
      size="lg"
      block
      disabled={disabled}
      onClick={onClick}
      className="relative gap-2"
    >
      <MethodIcon method={method} />
      {children}
      {tag ? (
        <span className="absolute right-3 text-xs font-normal text-muted-foreground">{tag}</span>
      ) : null}
    </Button>
  );
}
