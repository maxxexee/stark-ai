import { TabBarItem } from "@/components/shell/tab-bar-item";
import { TabBarTalkLink } from "@/components/shell/tab-bar-talk-link";
import { tabs } from "@/components/shell/tabs";

/** The phone's floating tab bar, over a blur that fades the page out beneath it. */
export function TabBar() {
  const [home, bills, activity, wallet] = tabs;
  return (
    <div className="pointer-events-none fixed inset-x-0 bottom-0 z-10 sm:hidden">
      <div
        aria-hidden
        className="absolute inset-x-0 bottom-0 h-32 bg-linear-to-t from-canvas/70 to-transparent backdrop-blur-md [mask-image:linear-gradient(to_top,black_45%,transparent)]"
      />
      <nav
        aria-label="App"
        className="pointer-events-auto relative mx-3 mb-[max(20px,env(safe-area-inset-bottom))] flex items-center rounded-3xl border border-border bg-canvas/85 px-1 py-1.5 shadow-[0_8px_24px_rgb(0_0_0/0.10)] backdrop-blur-lg"
      >
        <TabBarItem tab={home} />
        <TabBarItem tab={bills} />
        <TabBarTalkLink />
        <TabBarItem tab={activity} />
        <TabBarItem tab={wallet} />
      </nav>
    </div>
  );
}
