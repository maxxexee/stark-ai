import type { CryptoAsset, FundingMethods } from "@stark/api/types";
import { Networks } from "@/lib/wallet/networks";

/** What the Add money card's Send side can be: naira through a rail, or a crypto asset. */
export type SendOption =
  | { kind: "bank" }
  | { kind: "test" }
  | { kind: "crypto"; asset: CryptoAsset };

export type SendGroup = { value: string; items: SendOption[] };

export class SendOptions {
  static key(option: SendOption): string {
    return option.kind === "crypto" ? option.asset.asset_id : option.kind;
  }

  static label(option: SendOption): string {
    switch (option.kind) {
      case "bank":
        return "Naira";
      case "test":
        return "Test naira";
      case "crypto":
        return Networks.assetLabel(option.asset);
    }
  }

  static symbol(option: SendOption): string {
    return option.kind === "crypto" ? option.asset.symbol : "NGN";
  }

  static groups(methods: FundingMethods, assets: CryptoAsset[]): SendGroup[] {
    const naira: SendOption[] = [];
    if (methods.bank) naira.push({ kind: "bank" });
    if (methods.test_money) naira.push({ kind: "test" });

    const networks = methods.crypto
      ? Networks.group(assets).map((network) => ({
          value: network.value,
          items: network.items.map(
            (asset): SendOption => ({
              kind: "crypto",
              asset,
            }),
          ),
        }))
      : [];

    return naira.length ? [{ value: "Naira", items: naira }, ...networks] : networks;
  }
}
