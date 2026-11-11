import type { CryptoAsset } from "@stark/api/types";
import {
  Combobox,
  ComboboxCollection,
  ComboboxContent,
  ComboboxEmpty,
  ComboboxGroup,
  ComboboxInput,
  ComboboxItem,
  ComboboxLabel,
  ComboboxList,
  ComboboxTrigger,
  ComboboxValue,
} from "@stark/ui/components/combobox";
import { Field, FieldLabel } from "@stark/ui/components/field";
import { useId } from "react";
import { type NetworkGroup, Networks } from "@/lib/wallet/networks";

/** Searchable by symbol or network; the list is grouped by network. */
export function CryptoAssetSelect({
  label,
  placeholder,
  assets,
  value,
  onChange,
}: {
  label: string;
  placeholder: string;
  assets: CryptoAsset[];
  value: string;
  onChange: (assetId: string) => void;
}) {
  const id = useId();

  const handleAssetChange = (asset: CryptoAsset | null) => {
    if (asset) onChange(asset.asset_id);
  };

  return (
    <Field className="gap-2.5">
      <FieldLabel htmlFor={id} className="font-normal text-fg-2">
        {label}
      </FieldLabel>
      <Combobox
        items={Networks.group(assets)}
        value={assets.find((asset) => asset.asset_id === value) ?? null}
        onValueChange={handleAssetChange}
        itemToStringLabel={Networks.assetLabel}
      >
        <ComboboxTrigger
          id={id}
          className="flex h-12 w-full cursor-pointer items-center justify-between rounded-xl border border-input pr-3 pl-3.5 text-base outline-none transition-colors focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 data-placeholder:text-muted-foreground dark:bg-canvas dark:hover:bg-input/30"
        >
          <ComboboxValue placeholder={placeholder} />
        </ComboboxTrigger>
        <ComboboxContent className="min-w-(--anchor-width)">
          <ComboboxInput placeholder="Search coin or network" showTrigger={false} />
          <ComboboxEmpty>Nothing matches that.</ComboboxEmpty>
          <ComboboxList className="max-h-72">
            {(network: NetworkGroup) => (
              <ComboboxGroup key={network.value} items={network.items}>
                <ComboboxLabel>{network.value}</ComboboxLabel>
                <ComboboxCollection>
                  {(asset: CryptoAsset) => (
                    <ComboboxItem key={asset.asset_id} value={asset} className="py-2 pl-2.5">
                      {asset.symbol}
                    </ComboboxItem>
                  )}
                </ComboboxCollection>
              </ComboboxGroup>
            )}
          </ComboboxList>
        </ComboboxContent>
      </Combobox>
    </Field>
  );
}
