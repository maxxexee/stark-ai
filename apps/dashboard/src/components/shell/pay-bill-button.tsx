import { Button } from "@stark/ui/components/button";
import { Icons } from "@stark/ui/components/icons";
import { Link } from "@tanstack/react-router";

export function PayBillButton() {
  return (
    <Button
      size="sm"
      nativeButton={false}
      render={<Link to="/pay" aria-label="Pay a bill" />}
      className="w-8 px-0 text-white hover:text-white sm:w-auto sm:px-3"
    >
      <Icons.Add size={14} />
      <span className="hidden sm:inline">Pay a bill</span>
    </Button>
  );
}
