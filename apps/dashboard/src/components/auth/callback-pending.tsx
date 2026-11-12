export function CallbackPending({ pending }: { pending: boolean }) {
  return (
    <p className="m-0 mt-1.5 text-base text-muted-foreground">
      {pending ? "Finishing sign-in with Google…" : "Taking you in…"}
    </p>
  );
}
