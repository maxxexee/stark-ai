import { activityQuery, approvalsQuery, stateQuery, suggestionsQuery } from "@stark/api/queries";
import { noop, useQuery, useSuspenseQuery } from "@tanstack/react-query";
import { createFileRoute } from "@tanstack/react-router";
import { ApprovalsNotice } from "@/components/home/approvals-notice";
import { AskStark } from "@/components/home/ask-stark";
import { BalanceCard } from "@/components/home/balance-card";
import { DueNotice } from "@/components/home/due-notice";
import { HomeBills } from "@/components/home/home-bills";
import { HomeHeader } from "@/components/home/home-header";
import { LowMeterNotice } from "@/components/home/low-meter-notice";
import { NoticedCard } from "@/components/home/noticed-card";
import { RecentActivity } from "@/components/home/recent-activity";
import { Approvals } from "@/lib/approvals/approvals";
import { Bills } from "@/lib/bills/bills";
import { Renewals } from "@/lib/renewals/renewals";

export const Route = createFileRoute("/_app/")({
  loader: ({ context }) => {
    void context.queryClient.query(activityQuery()).catch(noop);
    void context.queryClient.query(approvalsQuery()).catch(noop);
  },
  head: () => ({ meta: [{ title: "Home · Stark" }] }),
  component: Home,
});

function Home() {
  const { data: state } = useSuspenseQuery(stateQuery());
  const { data: activity } = useQuery(activityQuery());
  const { data: suggestions } = useQuery(suggestionsQuery());
  const { data: requests } = useQuery(approvalsQuery());
  const waiting = Approvals.waiting(requests ?? []);
  const meter = Bills.meter(state);
  const low = meter && state.days_left !== null && state.days_left <= Bills.LOW_DAYS;
  const due = Renewals.next(state.due_soon);
  const noticed = (suggestions ?? []).filter(
    (sug) => !(low && sug.reason.startsWith("units_low")) && sug.id !== `sug_due_${due?.id}`,
  );
  const needing =
    Number(Boolean(low)) + Number(Boolean(due)) + Number(state.balance_ngn <= 0) + waiting.length;

  return (
    <>
      <HomeHeader firstName={state.first_name} needing={needing} paused={state.paused} />
      <ApprovalsNotice waiting={waiting} />
      <BalanceCard state={state} meter={meter} />
      {due ? <DueNotice due={due} /> : null}
      {low && meter ? <LowMeterNotice meter={meter} daysLeft={state.days_left} /> : null}
      {noticed.length ? <NoticedCard suggestions={noticed} /> : null}
      <AskStark />
      <HomeBills state={state} />
      <RecentActivity activity={activity} />
    </>
  );
}
