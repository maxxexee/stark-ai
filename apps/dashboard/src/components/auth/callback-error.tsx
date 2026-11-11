import { Button } from "@stark/ui/components/button";
import { Link, useNavigate } from "@tanstack/react-router";

export function CallbackError({ error }: { error: string }) {
  const navigate = useNavigate();
  return (
    <>
      <p role="alert" className="m-0 mt-1.5 text-base text-muted-foreground">
        {error}
      </p>
      <Button
        type="button"
        variant="brand"
        size="lg"
        block
        className="mt-6"
        onClick={() => navigate({ to: "/start" })}
      >
        Start again
      </Button>
      <p className="m-0 mt-3 text-sm text-muted-foreground">
        Or{" "}
        <Link to="/login" className="font-medium text-brand no-underline hover:text-brand-soft">
          log in with your email
        </Link>
        .
      </p>
    </>
  );
}
