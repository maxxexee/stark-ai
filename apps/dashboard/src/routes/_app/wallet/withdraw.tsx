import { errorCopy } from "@stark/api/errors";
import { banksQuery, fundingMethodsQuery, walletQuery } from "@stark/api/queries";
import type { Withdrawal } from "@stark/api/types";
import { PillTabs } from "@stark/ui/components/pill-tabs";
import { formatNaira } from "@stark/utils/format";
import { useQuery, useSuspenseQuery } from "@tanstack/react-query";
import { createFileRoute } from "@tanstack/react-router";
import { useState } from "react";
import { BackLink } from "@/components/shell/back-link";
import { PageTitle } from "@/components/shell/page-title";
import { CryptoWithdrawForm } from "@/components/wallet/crypto-withdraw-form";
import { WithdrawForm } from "@/components/wallet/withdraw-form";
import { WithdrawalResult } from "@/components/wallet/withdrawal-result";

type Method = "bank" | "crypto";

const LABELS: Record<Method, string> = { bank: "To a bank", crypto: "As crypto" };

export const Route = createFileRoute("/_app/wallet/withdraw")({
  loader: ({ context }) =>
    Promise.all([
      context.queryClient.query(walletQuery()),
      context.queryClient.query(fundingMethodsQuery()),
    ]),
  head: () => ({ meta: [{ title: "Withdraw · Stark" }] }),
  component: Withdraw,
});

function Withdraw() {
  const { data: wallet } = useSuspenseQuery(walletQuery());
  const { data: methods } = useSuspenseQuery(fundingMethodsQuery());
  const offered = (["bank", "crypto"] as const).filter((m) => methods.withdraw[m]);
  const [method, setMethod] = useState<Method>(offered[0] ?? "bank");
  const banks = useQuery({ ...banksQuery(), enabled: method === "bank" && methods.withdraw.bank });
  const [sent, setSent] = useState<Withdrawal | null>(null);

  return (
    <div className="flex w-full flex-col gap-6">
      <BackLink to="/wallet">Wallet</BackLink>
      <div className="flex flex-col gap-1.5">
        <PageTitle>Withdraw</PageTitle>
        <p className="m-0 text-fg-2">
          Send money out of your balance. You have {formatNaira(wallet.balance_ngn)}.
        </p>
      </div>
      {sent ? <WithdrawalResult withdrawal={sent} /> : null}
      {offered.length === 0 ? (
        <p className="m-0 text-fg-2">Withdrawing isn’t switched on here yet.</p>
      ) : null}
      {offered.length > 1 && !sent ? (
        <PillTabs
          label="How you’re withdrawing"
          tabs={offered.map((value) => ({ value, label: LABELS[value] }))}
          value={method}
          onChange={setMethod}
        />
      ) : null}
      {method === "bank" && banks.error ? (
        <p className="m-0 text-fg-2">{errorCopy(banks.error)}</p>
      ) : null}
      {method === "bank" && banks.data && !sent ? (
        <WithdrawForm banks={banks.data} balance={wallet.balance_ngn} onSent={setSent} />
      ) : null}
      {method === "crypto" && offered.includes("crypto") && !sent ? (
        <CryptoWithdrawForm balance={wallet.balance_ngn} onSent={setSent} />
      ) : null}
    </div>
  );
}
