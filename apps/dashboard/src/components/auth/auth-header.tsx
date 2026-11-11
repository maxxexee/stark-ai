import { LogoMark } from "@stark/ui/components/logo";
import { Link } from "@tanstack/react-router";

export function AuthHeader({ step }: { step?: string }) {
  return (
    <header className="flex items-center justify-between gap-4">
      <Link
        to="/"
        aria-label="Stark home"
        className="flex items-center gap-2.5 text-fg no-underline hover:text-fg"
      >
        <LogoMark size={20} cutout="#ffffff" />
        <span className="text-base font-semibold">Stark</span>
      </Link>
      {step ? <span className="tabular text-sm text-muted-foreground">{step}</span> : null}
    </header>
  );
}
