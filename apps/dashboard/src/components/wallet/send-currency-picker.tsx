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
} from "@stark/ui/components/combobox";
import type { RefObject } from "react";
import { Networks } from "@/lib/wallet/networks";
import { type SendGroup, type SendOption, SendOptions } from "@/lib/wallet/send-options";

/**
 * The list opens under the whole panel (`anchor`), as wide as it, searchable by coin or network.
 */
export function SendCurrencyPicker({
  groups,
  value,
  onChange,
  anchor,
  returnFocusTo,
}: {
  groups: SendGroup[];
  value: SendOption;
  onChange: (option: SendOption) => void;
  anchor: RefObject<HTMLDivElement | null>;
  returnFocusTo: RefObject<HTMLInputElement | null>;
}) {
  const handleOptionChange = (option: SendOption | null) => {
    if (option) onChange(option);
  };

  return (
    <Combobox
      items={groups}
      value={value}
      onValueChange={handleOptionChange}
      itemToStringLabel={SendOptions.label}
      isItemEqualToValue={(a: SendOption, b: SendOption) =>
        SendOptions.key(a) === SendOptions.key(b)
      }
    >
      <ComboboxTrigger
        aria-label={`Paying with ${SendOptions.label(value)}`}
        className="flex h-9 shrink-0 cursor-pointer items-center gap-1.5 rounded-lg bg-surface-2 pr-2 pl-3 text-base font-medium outline-none transition-colors hover:bg-surface-3 focus-visible:ring-3 focus-visible:ring-ring/50"
      >
        <span>{SendOptions.symbol(value)}</span>
        {value.kind === "crypto" ? (
          <span className="text-sm font-normal text-muted-foreground">
            {Networks.name(value.asset.chain)}
          </span>
        ) : null}
      </ComboboxTrigger>
      <ComboboxContent
        anchor={anchor}
        finalFocus={() => {
          requestAnimationFrame(() => returnFocusTo.current?.select());
          return returnFocusTo.current;
        }}
        className="min-w-(--anchor-width)"
      >
        <ComboboxInput placeholder="Search coin or network" showTrigger={false} />
        <ComboboxEmpty>Nothing matches that.</ComboboxEmpty>
        <ComboboxList className="max-h-72">
          {(group: SendGroup) => (
            <ComboboxGroup key={group.value} items={group.items}>
              <ComboboxLabel>{group.value}</ComboboxLabel>
              <ComboboxCollection>
                {(option: SendOption) => (
                  <ComboboxItem
                    key={SendOptions.key(option)}
                    value={option}
                    className="py-1.5 pl-2"
                  >
                    {option.kind === "crypto" ? option.asset.symbol : SendOptions.label(option)}
                  </ComboboxItem>
                )}
              </ComboboxCollection>
            </ComboboxGroup>
          )}
        </ComboboxList>
      </ComboboxContent>
    </Combobox>
  );
}
