import { useSetPaused } from "@stark/api/mutations";
import { stateQuery } from "@stark/api/queries";
import { Button } from "@stark/ui/components/button";
import { Icons } from "@stark/ui/components/icons";
import { Notice } from "@stark/ui/components/notice";
import { useQuery } from "@tanstack/react-query";

/**
 * Uses a plain query, not suspense: it also renders inside the error screen, where a state that
 * failed to load must not throw again.
 */
export function PausedBanner() {
  const { data: state } = useQuery(stateQuery());
  const setPaused = useSetPaused();

  if (!state?.paused) return null;

  const handleResume = () => setPaused.mutate(false);

  return (
    <Notice
      icon={<Icons.Pause size={16} />}
      title="Stark is paused"
      actions={
        <Button onClick={handleResume} disabled={setPaused.isPending}>
          Resume
        </Button>
      }
    >
      Nothing will be paid from any chat or the app until you resume.
    </Notice>
  );
}
