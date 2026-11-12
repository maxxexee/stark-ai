import { useConfirmBill } from "@stark/api/mutations";
import type { Bill } from "@stark/api/types";
import { Button } from "@stark/ui/components/button";

/** A bill Stark saved from a chat is only payable once its owner says yes here. */
export function ConfirmBillButton({ bill }: { bill: Bill }) {
  const confirm = useConfirmBill(bill.id);
  return (
    <Button onClick={() => confirm.mutate()} disabled={confirm.isPending}>
      Confirm bill
    </Button>
  );
}
