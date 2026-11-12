import type { Receipt } from "@stark/api/types";

export function ReceiptNote({ status }: { status: Receipt["status"] }) {
  if (status === "declined") {
    return (
      <p className="m-0 text-sm text-fg-2">
        Stark stopped this because it broke one of your rules. Nothing was charged.
      </p>
    );
  }
  if (status === "pending") {
    return (
      <p className="m-0 text-sm text-fg-2">
        Still going through at the provider. You haven’t been charged yet.
      </p>
    );
  }
  return null;
}
