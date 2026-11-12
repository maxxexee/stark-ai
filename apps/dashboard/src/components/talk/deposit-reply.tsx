import type { Deposit } from "@stark/api/types";
import { buttonVariants } from "@stark/ui/components/button";
import { CryptoPayInstructions } from "@/components/wallet/crypto-pay-instructions";

export function DepositReply({ deposit }: { deposit: Deposit }) {
  if (deposit.method === "crypto") return <CryptoPayInstructions pay={deposit.pay} />;
  return (
    <a href={deposit.pay.checkout_url} className={buttonVariants({ size: "lg", block: true })}>
      Continue to payment
    </a>
  );
}
