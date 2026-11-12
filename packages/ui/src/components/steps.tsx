export function Steps({ current, total = 3 }: { current: number; total?: number }) {
  return (
    <div
      role="progressbar"
      aria-label="Setup progress"
      aria-valuemin={1}
      aria-valuemax={total}
      aria-valuenow={current}
      className="flex gap-1"
    >
      {Array.from({ length: total }, (_, i) => (
        <span
          key={i}
          className={
            i < current ? "h-1 flex-1 rounded-full bg-brand" : "h-1 flex-1 rounded-full bg-track"
          }
        />
      ))}
    </div>
  );
}
