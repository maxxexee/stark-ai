export function CallbackPending({ pending }: { pending: boolean }) {
  return (
    <p className="m-0 mt-1.5 text-base text-muted-foreground">
      {pending ? "One moment — finishing the handshake with Google." : "Taking you in…"}
    </p>
  );
}
