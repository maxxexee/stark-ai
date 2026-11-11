import { usePayBill } from "@stark/api/mutations";
import { limitsQuery, stateQuery } from "@stark/api/queries";
import { AmountField } from "@stark/ui/components/amount-field";
import { useSuspenseQuery } from "@tanstack/react-query";
import { createFileRoute } from "@tanstack/react-router";
import { useState } from "react";
import { z } from "zod";
import { BillPicker } from "@/components/pay/bill-picker";
import { LimitHint } from "@/components/pay/limit-hint";
import { NothingToPay } from "@/components/pay/nothing-to-pay";
import { PayButton } from "@/components/pay/pay-button";
import { PayResult } from "@/components/pay/pay-result";
import { PayStats } from "@/components/pay/pay-stats";
import { PlanPriceCard } from "@/components/pay/plan-price-card";
import { Refused } from "@/components/pay/refused";
import { BackLink } from "@/components/shell/back-link";
import { PageTitle } from "@/components/shell/page-title";
import { Bills } from "@/lib/bills/bills";
import { PaymentLimits } from "@/lib/wallet/payment-limits";

export const Route = createFileRoute("/_app/pay")({
  validateSearch: z.object({
    bill: z.string().optional(),
    amount: z.number().int().positive().optional(),
  }),
  loader: ({ context }) => context.queryClient.query({ ...limitsQuery(), staleTime: "static" }),
  head: () => ({ meta: [{ title: "Pay a bill · Stark" }] }),
  component: Pay,
});

function Pay() {
  const { data: state } = useSuspenseQuery(stateQuery());
  const { data: limits } = useSuspenseQuery(limitsQuery());
  const search = Route.useSearch();
  const payable = state.bills.filter(Bills.isPayable);

  const [billId, setBillId] = useState(search.bill ?? payable[0]?.id);
  const bill = payable.find((b) => b.id === billId);
  const [typed, setTyped] = useState(search.amount ?? 5000);
  const amount = bill ? (Bills.fixedAmount(bill) ?? typed) : typed;
  const pay = usePayBill();

  const presets = PaymentLimits.presets(limits);
  const hint = PaymentLimits.hint(amount, limits, state);

  if (!payable.length) {
    return (
      <>
        <BackLink to="/">Home</BackLink>
        <PageTitle>Pay a bill</PageTitle>
        <NothingToPay />
      </>
    );
  }

  const handleBillChange = (id: string) => {
    pay.reset();
    setBillId(id);
  };

  const handleAmountChange = (value: number) => {
    pay.reset();
    setTyped(value);
  };

  const handlePayOffer = (offer: number) => {
    setTyped(offer);
    pay.reset();
  };

  const handlePay = () => bill && pay.mutate({ bill_id: bill.id, amount_ngn: amount });

  return (
    <div className="flex w-full flex-col gap-6">
      <BackLink to="/">Home</BackLink>
      <PageTitle>Pay a bill</PageTitle>

      <BillPicker bills={payable} state={state} value={billId} onValueChange={handleBillChange} />

      {bill && Bills.fixedAmount(bill) ? (
        <PlanPriceCard amount={amount} provider={bill.provider} />
      ) : (
        <AmountField label="Amount" value={typed} onChange={handleAmountChange} presets={presets} />
      )}

      {pay.data ? (
        <PayResult receipt={pay.data} bill={bill} onAgain={() => pay.reset()} />
      ) : (
        <div className="flex flex-col gap-4 border-t border-border pt-5">
          <PayStats remaining={limits.remaining_cap_ngn} amount={amount} />
          {pay.error ? (
            <Refused error={pay.error} onPay={handlePayOffer} />
          ) : (
            <LimitHint hint={hint} />
          )}
          <PayButton
            amount={amount}
            pending={pay.isPending}
            disabled={!bill || amount <= 0 || pay.isPending}
            onClick={handlePay}
          />
        </div>
      )}
    </div>
  );
}
