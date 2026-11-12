import type { Limits, State } from "@stark/api/types";
import { formatNaira } from "@stark/utils/format";

export class PaymentLimits {
  static presets(limits: Limits): number[] {
    return [2000, 5000, Math.min(limits.remaining_cap_ngn, limits.per_payment_cap_ngn)]
      .filter((v, i, a) => v > 0 && a.indexOf(v) === i)
      .sort((a, b) => a - b);
  }

  static hint(amount: number, limits: Limits, state: State): string | null {
    if (state.paused) return "Stark is paused. Resume it to pay.";
    if (amount > limits.per_payment_cap_ngn)
      return `That’s over your ${formatNaira(limits.per_payment_cap_ngn)} limit for one payment.`;
    if (amount > limits.remaining_cap_ngn)
      return `You have ${formatNaira(limits.remaining_cap_ngn)} left of this month’s limit.`;
    if (amount > state.balance_ngn) return `Your wallet has ${formatNaira(state.balance_ngn)}.`;
    return null;
  }
}
