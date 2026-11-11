import { CryptoPayInstructions } from "@/components/wallet/crypto-pay-instructions";
import { invalidateMoney } from "@stark/api/mutations";
import { depositQuery } from "@stark/api/queries";
import type { DepositStatus as Status } from "@stark/api/types";
import { Button, buttonVariants } from "@stark/ui/components/button";
import { Notice } from "@stark/ui/components/notice";
import { Spinner } from "@stark/ui/components/spinner";
import { formatNaira } from "@stark/utils/format";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";

type Pending = Extract<Status, "open" | "confirming">;

const BANK_WAITING: Record<Pending, string> = {
  open: "Already paid? It lands in your balance as soon as your bank confirms it.",
  confirming:
    "Payment received. It lands in your balance once your bank confirms it, so you can leave this page.",
};

export function DepositStatus({ depositId }: { depositId: string }) {
  const qc = useQueryClient();
  const {
    data: deposit,
    isError,
    isFetching,
    refetch,
  } = useQuery(depositQuery(depositId));

  useEffect(() => {
    if (deposit?.status === "credited") invalidateMoney(qc);
  }, [deposit?.status, qc]);

  if (!deposit) {
    if (!isError) return <Spinner />;
    return (
      <div className="flex flex-col gap-4">
        <Notice tone="muted" title="Couldn’t load this payment">
          Your money is safe. Try again in a moment.
        </Notice>
        <Button size="lg" block disabled={isFetching} onClick={() => refetch()}>
          Try again
        </Button>
      </div>
    );
  }

  switch (deposit.status) {
    case "credited":
      return (
        <Notice
          title={`${formatNaira(deposit.credited_ngn ?? deposit.amount_ngn)} added`}
        >
          It’s in your balance now.
        </Notice>
      );
    case "expired":
      return (
        <Notice tone="muted" title="This payment window closed">
          Nothing was taken. Start a new one to add money.
        </Notice>
      );
    case "failed":
    case "refunded":
      return (
        <Notice tone="muted" title="That payment didn’t go through">
          {deposit.status === "refunded"
            ? "What you sent is being returned. Nothing was added."
            : "Nothing was added to your balance."}
        </Notice>
      );
    case "open":
    case "confirming":
      if (deposit.method === "crypto") {
        return (
          <div className="flex flex-col gap-4">
            <CryptoPayInstructions pay={deposit.pay} />
            <p className="m-0 text-[13px] text-muted-foreground">
              Once you’ve sent it you can leave this page. It lands in your
              balance a few minutes after the swap completes.
            </p>
            <Button block disabled={isFetching} onClick={() => refetch()}>
              {isFetching ? <Spinner /> : null}
              I’ve sent it
            </Button>
          </div>
        );
      }
      return (
        <div className="flex flex-col gap-4">
          {deposit.status === "open" ? (
            <a
              href={deposit.pay.checkout_url}
              className={buttonVariants({ size: "lg", block: true })}
            >
              Continue to payment
            </a>
          ) : null}
          <p className="m-0 text-[13px] text-muted-foreground">
            {BANK_WAITING[deposit.status]}
          </p>
        </div>
      );
  }
}
