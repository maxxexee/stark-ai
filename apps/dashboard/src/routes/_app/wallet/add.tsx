import { fundingMethodsQuery } from "@stark/api/queries";
import { useSuspenseQuery } from "@tanstack/react-query";
import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { z } from "zod";
import { BackLink } from "@/components/shell/back-link";
import { PageTitle } from "@/components/shell/page-title";
import { AddMoneyForm } from "@/components/wallet/add-money-form";
import { AddMoneySteps } from "@/components/wallet/add-money-steps";
import { DepositStatus } from "@/components/wallet/deposit-status";

export const Route = createFileRoute("/_app/wallet/add")({
  validateSearch: z.object({
    deposit: z.string().optional(),
    amount: z.number().int().positive().catch(20000).default(20000),
    pay: z.string().optional(),
  }),
  loader: ({ context }) => context.queryClient.query(fundingMethodsQuery()),
  head: () => ({ meta: [{ title: "Add money · Stark" }] }),
  component: AddMoney,
});

function AddMoney() {
  const { deposit, amount, pay } = Route.useSearch();
  const navigate = useNavigate();
  const { data: methods } = useSuspenseQuery(fundingMethodsQuery());

  return (
    <div className="flex w-full flex-col gap-6">
      <BackLink to="/wallet">Wallet</BackLink>
      <div className="flex flex-col gap-1.5">
        <PageTitle>Add money</PageTitle>
        <p className="m-0 text-muted-foreground">
          Stark pays your bills from this balance. It’s ready to spend as soon as it lands.
        </p>
      </div>
      {deposit ? (
        <DepositStatus
          depositId={deposit}
          onBackToAmount={() => navigate({ to: ".", search: { amount, pay } })}
        />
      ) : (
        <>
          <AddMoneySteps current={1} />
          <AddMoneyForm
            methods={methods}
            initial={{ amount, option: pay }}
            onStarted={async (started, choice) => {
              await navigate({
                to: ".",
                search: { deposit: started.id, amount: choice.amount, pay: choice.option },
              });
              if (started.method === "bank") window.location.assign(started.pay.checkout_url);
            }}
            onTestMoneyAdded={() => navigate({ to: "/wallet" })}
          />
        </>
      )}
    </div>
  );
}
