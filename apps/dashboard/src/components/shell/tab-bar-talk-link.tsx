import { Icons } from "@stark/ui/components/icons";
import { Link } from "@tanstack/react-router";

export function TabBarTalkLink() {
  return (
    <Link
      to="/talk"
      aria-label="Talk to Stark"
      className="flex h-12 flex-1 items-center justify-center"
    >
      <span className="flex size-11 items-center justify-center rounded-full bg-brand text-white">
        <Icons.Mic size={22} />
      </span>
    </Link>
  );
}
