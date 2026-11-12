import { demoQuery } from "@stark/api/queries";
import { useSuspenseQuery } from "@tanstack/react-query";
import { createFileRoute } from "@tanstack/react-router";
import { DemoApproval } from "@/components/demo/demo-approval";
import { DemoHeader } from "@/components/demo/demo-header";
import { DemoLimits } from "@/components/demo/demo-limits";
import { DemoNotice } from "@/components/demo/demo-notice";
import { BalanceCard } from "@/components/home/balance-card";
import { DueNotice } from "@/components/home/due-notice";
import { HomeBills } from "@/components/home/home-bills";
import { HomeHeader } from "@/components/home/home-header";
import { RecentActivity } from "@/components/home/recent-activity";
import { Bills } from "@/lib/bills/bills";
import { Renewals } from "@/lib/renewals/renewals";

export const Route = createFileRoute("/demo")({
  loader: ({ context }) => context.queryClient.query({ ...demoQuery(), staleTime: "static" }),
  head: () => ({ meta: [{ title: "Sample account · Stark" }] }),
  component: Demo,
});

function Demo() {
  const { data } = useSuspenseQuery(demoQuery());
  const { state, approvals } = data;
  const due = Renewals.next(state.due_soon);

  return (
    <div className="flex min-h-dvh flex-col">
      <DemoHeader />
      <main className="mx-auto flex w-full max-w-190 flex-1 flex-col gap-6 px-4 pt-5 pb-10 sm:px-6 sm:pt-8">
        <DemoNotice />
        <div inert className="flex flex-col gap-6">
          <HomeHeader
            firstName={state.first_name}
            needing={approvals.length + Number(Boolean(due))}
            paused={state.paused}
          />
          {approvals.map((request) => (
            <DemoApproval key={request.id} request={request} />
          ))}
          <BalanceCard state={state} meter={Bills.meter(state)} />
          {due ? <DueNotice due={due} /> : null}
          <HomeBills state={state} />
          <RecentActivity activity={data.activity} />
        </div>
        <DemoLimits limits={data.limits} />
      </main>
    </div>
  );
}
