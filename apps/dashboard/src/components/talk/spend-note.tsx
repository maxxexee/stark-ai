import { PaymentMode } from "@/lib/receipts/payment-mode";

export function SpendNote() {
  return (
    <span className="text-center text-xs text-muted-foreground lg:text-left">
      Stark checks every payment against your limits.
      {PaymentMode.live ? "" : " Tokens are samples for now."}
    </span>
  );
}
