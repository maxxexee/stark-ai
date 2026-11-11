import { Icons } from "@stark/ui/components/icons";
import { TooltipTrigger } from "@stark/ui/components/tooltip";
import { Link } from "@tanstack/react-router";

// Round on purpose: it opens the voice orb, and the one circle in the dock marks it
// as the thing you talk to rather than another place to go.
export function DockTalkLink() {
  return (
    <TooltipTrigger
      content="Talk to Stark"
      render={
        <Link
          to="/talk"
          aria-label="Talk to Stark"
          className="pointer-events-auto flex size-12.5 items-center justify-center rounded-full bg-brand text-white shadow-[0_8px_24px_rgb(194_65_12/0.3)] hover:text-white"
        />
      }
    >
      <Icons.Mic size={20} />
    </TooltipTrigger>
  );
}
