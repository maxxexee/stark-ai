import { errorCopy } from "@stark/api/errors";
import { useUnlinkChat } from "@stark/api/mutations";
import type { LinkedChat } from "@stark/api/types";
import { Button } from "@stark/ui/components/button";
import { FieldError } from "@stark/ui/components/field";
import { ListRow, RowText } from "@stark/ui/components/list-row";
import { Spinner } from "@stark/ui/components/spinner";
import { formatShortDate } from "@stark/utils/format";

export function LinkedChatRow({ chat }: { chat: LinkedChat }) {
  const unlink = useUnlinkChat();
  return (
    <ListRow>
      <RowText
        title={chat.display_name ?? "Telegram chat"}
        subtitle={`Telegram ${chat.chat_hint} · linked ${formatShortDate(chat.linked_at)}`}
      />
      {unlink.error ? <FieldError className="text-sm">{errorCopy(unlink.error)}</FieldError> : null}
      <Button
        variant="destructive"
        size="sm"
        disabled={unlink.isPending}
        onClick={() => unlink.mutate(chat)}
      >
        {unlink.isPending ? <Spinner /> : null}
        Remove
      </Button>
    </ListRow>
  );
}
