import { Button } from "@stark/ui/components/button";
import { Icons } from "@stark/ui/components/icons";
import { Link } from "@tanstack/react-router";

export function AddAnotherBillButton() {
  return (
    <Button
      variant="outline"
      block
      nativeButton={false}
      render={<Link to="/bills/new" />}
      className="border-dashed bg-transparent text-fg-2 shadow-none"
    >
      <Icons.Add size={16} />
      Add internet, water or another meter
    </Button>
  );
}
