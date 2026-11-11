import { AccountAvatar } from "@/components/shell/account-avatar";
import { HeaderBreadcrumb } from "@/components/shell/header-breadcrumb";
import { PayBillButton } from "@/components/shell/pay-bill-button";

// The bar spans the window; its row sits in the page's column. Every control in it
// is 32px and vertically centred in the 52px bar.
export function AppHeader() {
  return (
    <header className="sticky top-0 z-10 border-b border-border bg-canvas/85 pt-[env(safe-area-inset-top)] backdrop-blur-lg">
      <div className="mx-auto flex h-13 w-full max-w-190 items-center gap-3 px-4 sm:px-6">
        <HeaderBreadcrumb />
        <div className="ml-auto flex items-center gap-2">
          <PayBillButton />
          <AccountAvatar />
        </div>
      </div>
    </header>
  );
}
