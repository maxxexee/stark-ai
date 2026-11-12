import type { Suggestion } from "@stark/api/types";
import { Card } from "@stark/ui/components/card";
import { Eyebrow } from "@stark/ui/components/eyebrow";
import { NoticedItem } from "@/components/home/noticed-item";

export function NoticedCard({ suggestions }: { suggestions: Suggestion[] }) {
  return (
    <Card className="gap-3">
      <Eyebrow>Stark noticed</Eyebrow>
      {suggestions.map((sug) => (
        <NoticedItem key={sug.id} suggestion={sug} />
      ))}
    </Card>
  );
}
