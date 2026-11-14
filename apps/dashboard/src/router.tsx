import { setApiBaseUrl, setAuthToken } from "@stark/api/client";
import { ApiError } from "@stark/api/errors";
import { MutationCache, QueryCache, QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createRouter } from "@tanstack/react-router";
import { sessionStore } from "./lib/auth/session-store";
import { routeTree } from "./routeTree.gen";

setApiBaseUrl(import.meta.env.VITE_STARK_API_URL ?? "");

setAuthToken(sessionStore.token());

export function getRouter() {
  const handleSignOutOfAuthorizedUser = (error: Error) => {
    if (!(error instanceof ApiError) || error.status !== 401 || !sessionStore.token()) return;
    sessionStore.forget();
    setAuthToken(null);
    queryClient.clear();
    void router.navigate({ to: "/login" });
  };

  const queryClient = new QueryClient({
    queryCache: new QueryCache({ onError: handleSignOutOfAuthorizedUser }),
    mutationCache: new MutationCache({ onError: handleSignOutOfAuthorizedUser }),
    defaultOptions: {
      queries: { staleTime: 15_000, retry: 1, refetchOnWindowFocus: true },
    },
  });

  const router = createRouter({
    routeTree,
    context: { queryClient },
    scrollRestoration: true,
    defaultPreload: "intent",
    defaultPreloadStaleTime: 0,
    Wrap: ({ children }) => (
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    ),
  });

  return router;
}

declare module "@tanstack/react-router" {
  interface Register {
    router: ReturnType<typeof getRouter>;
  }
}
