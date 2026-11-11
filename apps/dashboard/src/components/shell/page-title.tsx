import type { ReactNode } from "react";

export function PageTitle({ children, aside }: { children: ReactNode; aside?: ReactNode }) {
  return (
    <div className="flex min-h-9 flex-wrap items-center gap-3">
      <h1 className="m-0 text-2xl font-semibold tracking-tight">{children}</h1>
      {aside ? <div className="ml-auto">{aside}</div> : null}
    </div>
  );
}
