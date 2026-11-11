import { buttonVariants } from "@stark/ui/components/button";
import { Icons } from "@stark/ui/components/icons";
import { cn } from "@stark/ui/utils/cn";

export function TelegramDeepLink({
  href,
  botUsername,
}: {
  href: string;
  botUsername: string | null;
}) {
  return (
    <a
      href={href}
      target="_blank"
      rel="noreferrer"
      className={cn(buttonVariants(), "self-start text-white hover:text-white")}
    >
      <Icons.Telegram size={16} />
      Open @{botUsername} in Telegram
    </a>
  );
}
