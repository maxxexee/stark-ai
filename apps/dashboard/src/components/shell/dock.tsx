import { DockTab } from "@/components/shell/dock-tab";
import { DockTalkLink } from "@/components/shell/dock-talk-link";
import { tabs } from "@/components/shell/tabs";

// Tabs are 40px; the bar is 50px with its padding and border, and the Talk button
// beside it is 50px too, so both share one top, bottom and midline.
export function Dock() {
  return (
    <div className="pointer-events-none fixed inset-x-0 bottom-5 z-10 hidden items-center justify-center gap-2 sm:flex">
      <nav
        aria-label="App"
        className="pointer-events-auto flex gap-1 rounded-card border border-border bg-canvas/90 p-1 shadow-[0_8px_24px_rgb(0_0_0/0.08)] backdrop-blur-lg"
      >
        {tabs.map((tab) => (
          <DockTab key={tab.to} tab={tab} />
        ))}
      </nav>
      <DockTalkLink />
    </div>
  );
}
