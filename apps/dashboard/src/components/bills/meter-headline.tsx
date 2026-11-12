import { Eyebrow } from "@stark/ui/components/eyebrow";

export function MeterHeadline({ daysLeft }: { daysLeft: number }) {
  return (
    <>
      <Eyebrow>Light left</Eyebrow>
      <div className="flex flex-wrap items-baseline gap-2">
        <span className="tabular text-3xl font-semibold tracking-tight">About {daysLeft} days</span>
        <span className="text-sm text-muted-foreground">estimated from your top-ups</span>
      </div>
    </>
  );
}
