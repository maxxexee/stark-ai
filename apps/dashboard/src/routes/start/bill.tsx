import { Button } from "@stark/ui/components/button";
import { createFileRoute, Link, useNavigate } from "@tanstack/react-router";
import { BillForm } from "@/components/bills/bill-form";
import { PaysWhenAskedNote } from "@/components/bills/pays-when-asked-note";
import { OnboardingShell } from "@/components/shell/onboarding-shell";

export const Route = createFileRoute("/start/bill")({
  head: () => ({ meta: [{ title: "Your first bill · Stark" }] }),
  component: FirstBill,
});

function FirstBill() {
  const navigate = useNavigate();
  return (
    <OnboardingShell
      step={2}
      title="What should Stark pay first?"
      lead="You can add more bills later, or just ask Stark."
    >
      <BillForm onAdded={() => navigate({ to: "/start/money" })} footer={<PaysWhenAskedNote />} />
      <Button
        variant="ghost"
        nativeButton={false}
        render={<Link to="/start/money" />}
        className="self-center"
      >
        Skip for now
      </Button>
    </OnboardingShell>
  );
}
