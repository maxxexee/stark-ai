import { approvalsQuery } from "@stark/api/queries";
import { RowList } from "@stark/ui/components/list-row";
import { SectionHeading } from "@stark/ui/components/section-heading";
import { useSuspenseQuery } from "@tanstack/react-query";
import { createFileRoute } from "@tanstack/react-router";
import { ApprovalCard } from "@/components/approvals/approval-card";
import { ApprovalHistoryRow } from "@/components/approvals/approval-history-row";
import { ApprovalsEmpty } from "@/components/approvals/approvals-empty";
import { PageTitle } from "@/components/shell/page-title";
import { Approvals } from "@/lib/approvals/approvals";

export const Route = createFileRoute("/_app/approvals")({
  loader: ({ context }) => context.queryClient.query({ ...approvalsQuery(), staleTime: "static" }),
  head: () => ({ meta: [{ title: "Approvals · Stark" }] }),
  component: ApprovalsPage,
});

function ApprovalsPage() {
  const { data: requests } = useSuspenseQuery(approvalsQuery());
  const waiting = Approvals.waiting(requests);
  const decided = requests.filter((r) => !waiting.includes(r));

  return (
    <>
      <PageTitle>Approvals</PageTitle>
      <p className="m-0 text-base text-muted-foreground">
        When you ask Stark for more than your limits allow, it asks you here first. Only this app
        can approve a payment, never a chat.
      </p>

      {waiting.map((request) => (
        <ApprovalCard key={request.id} request={request} />
      ))}
      {!requests.length ? <ApprovalsEmpty /> : null}

      {decided.length ? (
        <>
          <SectionHeading>Earlier</SectionHeading>
          <RowList>
            {decided.map((request) => (
              <ApprovalHistoryRow key={request.id} request={request} />
            ))}
          </RowList>
        </>
      ) : null}
    </>
  );
}
