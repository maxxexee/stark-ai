import { errorCopy } from "@stark/api/errors";
import { useLinkCode } from "@stark/api/mutations";
import { Button } from "@stark/ui/components/button";
import { Card } from "@stark/ui/components/card";
import { FieldError } from "@stark/ui/components/field";
import { Icons } from "@stark/ui/components/icons";
import { Spinner } from "@stark/ui/components/spinner";
import { createFileRoute } from "@tanstack/react-router";
import { ConnectIntro } from "@/components/connect/connect-intro";
import { ConnectSteps } from "@/components/connect/connect-steps";
import { MintedCode } from "@/components/connect/minted-code";
import { WhyCodeCard } from "@/components/connect/why-code-card";
import { PageTitle } from "@/components/shell/page-title";

export const Route = createFileRoute("/_app/connect")({
  head: () => ({ meta: [{ title: "Connect a chat · Stark" }] }),
  component: Connect,
});

/**
 * Mints a link code for the account signed in here, so a chat that spends it acts only for that
 * account and every sign-up links its own Telegram.
 */
function Connect() {
  const link = useLinkCode();
  const minted = link.data;

  return (
    <>
      <PageTitle>Connect a chat</PageTitle>

      <Card className="gap-3.5">
        <ConnectIntro />
        <ConnectSteps minted={minted !== undefined} />

        {minted ? <MintedCode minted={minted} /> : null}

        {link.error ? <FieldError className="text-sm">{errorCopy(link.error)}</FieldError> : null}

        <Button onClick={() => link.mutate()} disabled={link.isPending} className="self-start">
          {link.isPending ? <Spinner /> : <Icons.Telegram size={16} />}
          {minted ? "Get another code" : "Get a code"}
        </Button>
      </Card>

      <WhyCodeCard />
    </>
  );
}
