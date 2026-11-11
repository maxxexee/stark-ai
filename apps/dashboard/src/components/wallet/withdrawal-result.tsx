import type { Withdrawal } from "@stark/api/types";
import { Notice } from "@stark/ui/components/notice";
import { formatNaira } from "@stark/utils/format";

const BANK_COPY: Record<
  Extract<Withdrawal, { method: "bank" }>["status"],
  string
> = {
  sending: "Sending it to your bank now.",
  processing: "On its way to your bank.",
  paid: "It’s in your bank account.",
  returned: "It couldn’t be sent, so it’s back in your balance.",
};

function copy(withdrawal: Withdrawal): string {
  if (withdrawal.method === "bank") return BANK_COPY[withdrawal.status];
  const { amount, asset } = withdrawal.crypto;
  switch (withdrawal.status) {
    case "sending":
      return `About ${amount} ${asset} is going out now.`;
    case "processing":
      return `About ${amount} ${asset} is on its way to your address.`;
    case "paid":
      return `${amount} ${asset} arrived at your address.`;
    case "returned":
      return "It couldn’t be sent, so it’s back in your balance.";
  }
}

export function WithdrawalResult({ withdrawal }: { withdrawal: Withdrawal }) {
  return (
    <Notice
      tone={withdrawal.status === "returned" ? "muted" : "brand"}
      title={`${formatNaira(withdrawal.amount_ngn)} withdrawal`}
    >
      {copy(withdrawal)}
      {withdrawal.note ? ` ${withdrawal.note}` : null}
    </Notice>
  );
}
