import type { PaymentRequest } from "@stark/api/types";
import { Link } from "@tanstack/react-router";
import { ApprovalCard } from "@/components/approvals/approval-card";

export function ApprovalsNotice({ waiting }: { waiting: PaymentRequest[] }) {
  const [first, ...rest] = waiting;
  if (!first) return null;

  return (
    <section className="flex flex-col gap-2">
      <ApprovalCard request={first} />
      {rest.length ? (
        <Link to="/approvals" className="self-start text-sm">
          {rest.length === 1 ? "One more is waiting" : `${rest.length} more are waiting`}
        </Link>
      ) : null}
    </section>
  );
}
