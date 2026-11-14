import type { Bill, State } from "@stark/api/types";
import { formatNaira, formatShortDate, maskReference } from "@stark/utils/format";
import { BillKinds } from "@/lib/bills/bill-kinds";
import { Renewals } from "@/lib/renewals/renewals";

export type BillStatus = { text: string; attention: boolean };

export class Bills {
  static readonly LOW_DAYS = 5;

  static meter(state: State): Bill | undefined {
    return state.bills.find((b) => b.kind === "electricity");
  }

  static subtitle(bill: Bill): string {
    const parts = [BillKinds.label(bill.kind), bill.provider];
    if (bill.kind === "electricity") parts.push(`meter ${maskReference(bill.reference)}`);
    if (bill.kind === "airtime" || bill.kind === "data") parts.push(maskReference(bill.reference));
    return parts.join(" · ");
  }

  static status(bill: Bill, state: State): BillStatus {
    if (
      bill.kind === "electricity" &&
      Bills.meter(state)?.id === bill.id &&
      state.days_left !== null
    ) {
      return {
        text: `About ${state.days_left} day${state.days_left === 1 ? "" : "s"} left`,
        attention: state.days_left <= Bills.LOW_DAYS,
      };
    }
    if (bill.kind === "internet" || bill.kind === "water") {
      return { text: "Saved, paying soon", attention: false };
    }

    if (bill.renews_on) {
      const day = Renewals.day(bill.renews_on);
      if (day) {
        return {
          text: `Renews ${day}`,
          attention: (state.due_soon ?? []).some((item) => item.id === bill.id),
        };
      }
    }

    if (bill.plan_price_ngn) {
      return {
        text: bill.last_paid_at
          ? `${formatNaira(bill.plan_price_ngn)} plan · paid ${formatShortDate(bill.last_paid_at)}`
          : `${formatNaira(bill.plan_price_ngn)} plan`,
        attention: false,
      };
    }
    if (bill.last_paid_at) {
      return {
        text: `Last paid ${formatShortDate(bill.last_paid_at)}`,
        attention: false,
      };
    }
    return { text: "Not paid yet", attention: false };
  }

  static isPayable(bill: Pick<Bill, "kind">): boolean {
    return bill.kind !== "internet" && bill.kind !== "water";
  }

  static fixedAmount(bill: Bill): number | null {
    return bill.plan_price_ngn ?? null;
  }
}
