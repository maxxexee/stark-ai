import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { BillForm } from "@/components/bills/bill-form";
import { BackLink } from "@/components/shell/back-link";
import { PageTitle } from "@/components/shell/page-title";

export const Route = createFileRoute("/_app/bills/new")({
  head: () => ({ meta: [{ title: "Add a bill · Stark" }] }),
  component: NewBill,
});

function NewBill() {
  const navigate = useNavigate();
  return (
    <div className="flex w-full flex-col gap-6">
      <BackLink to="/bills">Bills</BackLink>
      <div className="flex flex-col gap-1">
        <PageTitle>Add a bill</PageTitle>
        <p className="m-0 text-base text-muted-foreground">
          Stark can pay it as soon as it’s saved.
        </p>
      </div>
      <BillForm
        onAdded={(bill) => navigate({ to: "/bills/$billId", params: { billId: bill.id } })}
      />
    </div>
  );
}
