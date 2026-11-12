import { TooltipProvider } from "@stark/ui/components/tooltip";
import type { ReactNode } from "react";
import { AppHeader } from "@/components/shell/app-header";
import { Dock } from "@/components/shell/dock";
import { PausedBanner } from "@/components/shell/paused-banner";
import { TabBar } from "@/components/shell/tab-bar";

export function AppShell({ children }: { children: ReactNode }) {
  return (
    <TooltipProvider>
      <div className="flex min-h-dvh flex-col">
        <AppHeader />
        <main className="mx-auto flex w-full max-w-190 flex-1 flex-col gap-6 px-4 pt-5 pb-36 sm:px-6 sm:pt-8 sm:pb-28">
          <PausedBanner />
          {children}
        </main>
        <Dock />
        <TabBar />
      </div>
    </TooltipProvider>
  );
}
