export function OnboardingHeading({ title, lead }: { title: string; lead: string }) {
  return (
    <div className="flex flex-col gap-1.5">
      <h1 className="m-0 text-2xl font-semibold tracking-tight">{title}</h1>
      <p className="m-0 text-base text-muted-foreground">{lead}</p>
    </div>
  );
}
