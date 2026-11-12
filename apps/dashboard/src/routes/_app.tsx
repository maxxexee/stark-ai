import { stateQuery } from "@stark/api/queries";
import { createFileRoute, Outlet, redirect } from "@tanstack/react-router";
import { QueryError } from "@/components/query-error";
import { AppShell } from "@/components/shell/app-shell";
import { sessionStore } from "@/lib/auth/session-store";

export const Route = createFileRoute("/_app")({
  beforeLoad: () => {
    if (!sessionStore.token()) throw redirect({ to: "/login" });
  },
  loader: ({ context }) => context.queryClient.query({ ...stateQuery(), staleTime: "static" }),
  component: () => (
    <AppShell>
      <Outlet />
    </AppShell>
  ),
  errorComponent: (props) => (
    <AppShell>
      <QueryError {...props} />
    </AppShell>
  ),
});
