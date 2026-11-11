import { LogoMark } from "@stark/ui/components/logo";
import { Link } from "@tanstack/react-router";

export function OnboardingHeader({ step }: { step: 1 | 2 | 3 }) {
  return (
    <header className="flex h-13 items-center gap-2.5 border-b border-border px-4 sm:px-6">
      <Link
        to="/"
        aria-label="Stark home"
        className="flex items-center gap-2.5 text-fg no-underline hover:text-fg"
      >
        <LogoMark size={20} cutout="#ffffff" />
        <span className="text-base font-semibold">Stark</span>
      </Link>
      <span aria-hidden="true" className="text-faint">
        /
      </span>
      <span className="text-base text-fg-2">Get started</span>
      <span className="tabular ml-auto text-sm text-muted-foreground">Step {step} of 3</span>
    </header>
  );
}
