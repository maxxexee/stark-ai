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
 * The app half of identity linking. The bot only trusts a chat bound in
 * `identities.py`, and a code is the only thing that binds it — so this screen
 * is the door: mint one, hand it over, done.
 *
 * The code belongs to the account that is signed in here, not to the bot's
 * owner: `POST /v1/link/code` mints against the bearer's account, and a chat
 * then acts only for the account whose code it spent. That is what lets every
 * new sign-up link its own Telegram instead of sharing the owner's wallet.
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
