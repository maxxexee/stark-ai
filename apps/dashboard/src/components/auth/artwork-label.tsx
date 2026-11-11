export function ArtworkLabel() {
  return (
    <div className="absolute inset-x-0 top-0 z-10 p-4 lg:p-5">
      <span className="inline-flex h-7 items-center gap-2 rounded-lg bg-fg/85 px-2.5 backdrop-blur-sm">
        <span className="size-1.5 rounded-full bg-brand" />
        <span className="text-xs font-medium text-canvas">Prepaid power, handled</span>
      </span>
    </div>
  );
}
