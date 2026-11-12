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
    <Field className="gap-2">
      <FieldLabel htmlFor={id} className="text-sm font-medium text-fg-2">
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
          className="flex h-9 w-full cursor-pointer items-center justify-between rounded-lg border border-input bg-card pr-2.5 pl-3 text-base shadow-control outline-none transition-colors hover:bg-muted focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 data-placeholder:text-muted-foreground"
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
                    <ComboboxItem key={asset.asset_id} value={asset} className="py-1.5 pl-2">
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
