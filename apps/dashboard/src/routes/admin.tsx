import { createFileRoute } from "@tanstack/react-router";
import { useCallback, useState } from "react";
import { AdminKeyForm } from "@/components/admin/admin-key-form";
import { AdminOverview } from "@/components/admin/admin-overview";
import { AdminApi } from "@/lib/admin/admin-api";

export const Route = createFileRoute("/admin")({
  // The key lives in sessionStorage, which only the browser has.
  ssr: false,
  head: () => ({
    meta: [{ title: "Admin · Stark" }, { name: "robots", content: "noindex, nofollow" }],
  }),
  component: Admin,
});

function Admin() {
  const [adminKey, setAdminKey] = useState(AdminApi.savedKey);
  const [refusal, setRefusal] = useState<string | null>(null);

  const lock = useCallback(() => {
    AdminApi.forgetKey();
    setAdminKey(null);
  }, []);
  const refused = useCallback(
    (message: string) => {
      lock();
      setRefusal(message);
    },
    [lock],
  );

  return (
    <main className="mx-auto flex min-h-dvh w-full max-w-240 flex-col gap-6 px-4 pt-8 pb-10 sm:px-6">
      <h1 className="m-0 text-2xl font-semibold tracking-tight">Stark admin</h1>
      {adminKey ? (
        <AdminOverview adminKey={adminKey} onRefused={refused} onLock={lock} />
      ) : (
        <AdminKeyForm
          error={refusal}
          onSubmit={(key) => {
            AdminApi.saveKey(key);
            setRefusal(null);
            setAdminKey(key);
          }}
        />
      )}
    </main>
  );
}
