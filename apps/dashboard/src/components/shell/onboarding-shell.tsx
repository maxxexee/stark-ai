import { Steps } from "@stark/ui/components/steps";
import type { ReactNode } from "react";
import { OnboardingHeader } from "@/components/shell/onboarding-header";
import { OnboardingHeading } from "@/components/shell/onboarding-heading";

export function OnboardingShell({
  step,
  title,
  lead,
  children,
}: {
  step: 1 | 2 | 3;
  title: string;
  lead: string;
  children: ReactNode;
}) {
  return (
    <div className="flex min-h-dvh flex-col">
      <OnboardingHeader step={step} />
      <main className="mx-auto flex w-full max-w-120 flex-col gap-6 px-4 pt-8 pb-16 sm:px-6 sm:pt-12">
        <Steps current={step} />
        <OnboardingHeading title={title} lead={lead} />
        {children}
      </main>
    </div>
  );
}
