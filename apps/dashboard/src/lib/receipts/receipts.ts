import type { Receipt } from "@stark/api/types";

export type StatusDisplay = { label: string; tone: "brand" | "muted" | "fg" };

export type ActivityFilter = "all" | "bills" | "in" | "declined";

export class Receipts {
  static status(r: Receipt): StatusDisplay {
    switch (r.status) {
      case "delivered":
        return { label: "Paid", tone: "brand" };
      case "pending":
        return { label: "Going through", tone: "fg" };
      case "failed":
        return { label: "Didn’t go through", tone: "muted" };
      case "declined":
        return { label: "Declined", tone: "muted" };
      case "received":
        return { label: "Received", tone: "muted" };
      case "sent":
        return { label: "Sent", tone: "muted" };
    }
  }

  static subtitle(r: Receipt): string {
    if (r.status === "declined") return `${r.reason ?? "Stark stopped this."} Nothing was charged.`;
    if (r.status === "failed") return "Nothing was charged";
    if (r.status === "pending") return "Still going through. Not paid yet.";
    if (r.type === "withdrawal") return r.source ?? "To your bank";
    return r.source ?? "";
  }

  /** What the entry moved: a bill counts its service fee, since the wallet paid both. */
  static signedAmount(r: Receipt): number {
    if (r.type === "deposit") return r.amount_ngn;
    if (r.type === "withdrawal") return -r.amount_ngn;
    return r.amount_ngn + (r.fee_ngn ?? 0);
  }

  static matchesFilter(r: Receipt, filter: ActivityFilter): boolean {
    switch (filter) {
      case "all":
        return true;
      case "bills":
        return (r.type === "bill" || r.type === "autotopup") && r.status === "delivered";
      case "in":
        return r.type === "deposit";
      case "declined":
        return r.status === "declined" || r.status === "failed";
    }
  }
}
