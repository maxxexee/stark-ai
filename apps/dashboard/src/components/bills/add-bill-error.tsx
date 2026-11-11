import { errorCopy } from "@stark/api/errors";
import { FieldError } from "@stark/ui/components/field";
import { Icons } from "@stark/ui/components/icons";

export function AddBillError({ error }: { error: Error }) {
  return (
    <FieldError className="flex items-center gap-2 text-sm">
      <Icons.Warning size={16} />
      {errorCopy(error)}
    </FieldError>
  );
}
