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

/** The Send side's currency pill. The list opens under the whole panel (`anchor`), as wide
 * as it, searchable by coin or network and grouped by network. */
export function SendCurrencyPicker({
  groups,
  value,
  onChange,
  anchor,
}: {
  groups: SendGroup[];
  value: SendOption;
  onChange: (option: SendOption) => void;
  anchor: RefObject<HTMLDivElement | null>;
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
        className="flex h-10 shrink-0 cursor-pointer items-center gap-2 rounded-full bg-surface pr-3 pl-3.5 text-[15px] font-medium outline-none transition-colors hover:bg-input/40 focus-visible:ring-3 focus-visible:ring-ring/50"
      >
        <span>{SendOptions.symbol(value)}</span>
        {value.kind === "crypto" ? (
          <span className="text-[13px] font-normal text-muted-foreground">
            {Networks.name(value.asset.chain)}
          </span>
        ) : null}
      </ComboboxTrigger>
      <ComboboxContent anchor={anchor} className="min-w-(--anchor-width)">
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
                    className="py-2 pl-2.5"
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
