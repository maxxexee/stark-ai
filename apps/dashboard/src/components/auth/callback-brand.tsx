import { LogoMark } from "@stark/ui/components/logo";
import { Link } from "@tanstack/react-router";

export function CallbackBrand() {
  return (
    <Link to="/" className="flex items-center gap-2.5 text-fg no-underline hover:text-fg">
      <LogoMark size={20} cutout="#ffffff" />
      <span className="text-base font-semibold">Stark</span>
    </Link>
  );
}
