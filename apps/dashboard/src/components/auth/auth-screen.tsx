import type { ReactNode } from "react";
import { ArtworkPanel } from "@/components/auth/artwork-panel";
import { AuthHeader } from "@/components/auth/auth-header";
import { LimitsNote } from "@/components/auth/limits-note";

export function AuthScreen({ step, children }: { step?: string; children: ReactNode }) {
  return (
    <div className="relative grid min-h-dvh w-full bg-canvas lg:grid-cols-[48%_52%]">
      <ArtworkPanel />

      <div className="relative flex min-h-dvh flex-col px-4 py-10 sm:px-10 lg:px-14 xl:px-20">
        <div className="mx-auto flex w-full max-w-117.5 flex-1 flex-col justify-center">
          <AuthHeader step={step} />
          {children}
          <LimitsNote />
        </div>
      </div>
    </div>
  );
}
