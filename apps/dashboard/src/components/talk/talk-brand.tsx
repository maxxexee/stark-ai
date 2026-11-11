import { LogoMark } from "@stark/ui/components/logo";

export function TalkBrand() {
  return (
    <span className="flex items-center gap-2.5">
      <LogoMark size={20} cutout="#111214" />
      <span className="text-base font-semibold">Stark</span>
    </span>
  );
}
