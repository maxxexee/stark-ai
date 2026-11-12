import type { BillKind } from "@stark/api/types";
import type { IconName } from "@stark/ui/components/icons";

export class BillKinds {
  static readonly all: { kind: BillKind; label: string; icon: IconName }[] = [
    { kind: "electricity", label: "Electricity", icon: "Electricity" },
    { kind: "airtime", label: "Airtime", icon: "Airtime" },
    { kind: "data", label: "Data", icon: "Data" },
    { kind: "tv", label: "Cable TV", icon: "Tv" },
    { kind: "internet", label: "Internet", icon: "Internet" },
    { kind: "water", label: "Water", icon: "Water" },
  ];

  static readonly referenceLabel: Record<BillKind, string> = {
    electricity: "Meter number",
    airtime: "Phone number",
    data: "Phone number",
    tv: "Smartcard number",
    internet: "Account number",
    water: "Account number",
  };

  static readonly providers: Record<BillKind, string[]> = {
    electricity: [
      "Ikeja Electric",
      "Eko Electric",
      "Abuja Electric",
      "Ibadan Electric",
      "Enugu Electric",
      "Benin Electric",
      "Port Harcourt Electric",
      "Kano Electric",
      "Kaduna Electric",
      "Jos Electric",
    ],
    airtime: ["MTN", "Airtel", "Glo", "9mobile"],
    data: ["MTN", "Airtel", "Glo", "9mobile"],
    tv: ["DStv", "GOtv", "Startimes"],
    internet: ["Spectranet", "Smile", "Other"],
    water: ["Lagos Water Corporation", "Other"],
  };

  static readonly defaultNickname: Record<BillKind, string> = {
    electricity: "Home",
    airtime: "My line",
    data: "My data",
    tv: "Living room TV",
    internet: "Wi-Fi",
    water: "Water",
  };

  static label(kind: BillKind): string {
    return BillKinds.all.find((k) => k.kind === kind)?.label ?? kind;
  }

  static icon(kind: BillKind): IconName {
    return BillKinds.all.find((k) => k.kind === kind)?.icon ?? "Bills";
  }
}
