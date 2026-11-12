import type { QueryClient } from "@tanstack/react-query";
import { createRootRouteWithContext, Outlet } from "@tanstack/react-router";
import { NotFound } from "@/components/root/not-found";
import { RootDocument } from "@/components/root/root-document";
import styles from "../styles.css?url";

export const Route = createRootRouteWithContext<{ queryClient: QueryClient }>()({
  head: () => ({
    meta: [
      { charSet: "utf-8" },
      {
        name: "viewport",
        content: "width=device-width, initial-scale=1, viewport-fit=cover",
      },
      { name: "theme-color", content: "#ffffff" },
      { title: "Stark" },
      {
        name: "description",
        content: "Stark pays your everyday bills, within limits you set.",
      },
    ],
    links: [
      { rel: "stylesheet", href: styles },
      {
        rel: "icon",
        href: "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24'%3E%3Cpath fill='%23C2410C' d='M12 1.5c-4.6 0-8.3 3.3-8.3 7.9V15c0 1.5.7 2.9 1.8 3.8L9 22h6l3.5-3.2A4.9 4.9 0 0020.3 15V9.4c0-4.6-3.7-7.9-8.3-7.9z'/%3E%3C/svg%3E",
      },
    ],
  }),
  component: RootComponent,
  notFoundComponent: NotFound,
});

function RootComponent() {
  return (
    <RootDocument>
      <Outlet />
    </RootDocument>
  );
}
