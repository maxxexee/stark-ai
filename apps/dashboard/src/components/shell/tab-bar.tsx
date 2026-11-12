import { TabBarItem } from "@/components/shell/tab-bar-item";
import { TabBarTalkLink } from "@/components/shell/tab-bar-talk-link";
import { tabs } from "@/components/shell/tabs";

export function TabBar() {
  const [home, bills, activity, wallet] = tabs;
  return (
    <nav
      aria-label="App"
      className="sticky bottom-0 z-10 flex items-center border-t border-border bg-canvas/90 px-2 pt-1.5 pb-[max(8px,env(safe-area-inset-bottom))] backdrop-blur-lg sm:hidden"
    >
      <TabBarItem tab={home} />
      <TabBarItem tab={bills} />
      <TabBarTalkLink />
      <TabBarItem tab={activity} />
      <TabBarItem tab={wallet} />
    </nav>
  );
}
