export function CallbackTitle({ error }: { error: string | null }) {
  return (
    <h1 className="m-0 mt-8 text-2xl font-semibold tracking-tight text-fg">
      {error ? "That did not go through" : "Signing you in"}
      <span className="text-brand">.</span>
    </h1>
  );
}
