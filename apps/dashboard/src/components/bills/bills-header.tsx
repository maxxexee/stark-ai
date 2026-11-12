import { Button } from "@stark/ui/components/button";
import { Icons } from "@stark/ui/components/icons";
import { Link } from "@tanstack/react-router";
import { PageTitle } from "@/components/shell/page-title";

export function BillsHeader() {
  return (
    <>
      <PageTitle
        aside={
          <Button nativeButton={false} render={<Link to="/bills/new" />}>
            <Icons.Add size={14} />
            Add a bill
          </Button>
        }
      >
        Bills
      </PageTitle>
      <p className="m-0 -mt-4 text-base text-muted-foreground">
        Stark watches these and tells you before anything runs out.
      </p>
    </>
  );
}
