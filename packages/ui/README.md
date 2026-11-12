# @stark/ui

Stark's design system, shared by the dashboard and the website. It is
[shadcn/ui](https://ui.shadcn.com) with the **Base UI** primitives (`base-nova` style),
themed to Stark, plus a few Stark-specific pieces built on top.

## Using it

```tsx
import { Button } from "@stark/ui/components/button";
import { Icons } from "@stark/ui/components/icons";
import { cn } from "@stark/ui/utils/cn";
```

Each app imports the theme once from its stylesheet, after Tailwind:

```css
@import "tailwindcss";
@import "@stark/ui/globals.css";
```

The light theme (`:root`) is the website's paper and ink. The dashboard puts `class="dark"`
on `<html>` for the near-black app theme, where the primary colour is burnt orange.

## What's in it

- `src/components/*`: every shadcn component except `slider` (Stark never uses sliders),
  restyled where Stark differs, with pill buttons with `brand`, `light`, `ink` and `paper`
  variants, 48px inputs, 20px card padding, Crimson Pro titles in cards, dialogs and sheets.
- Stark pieces built on them: `amount-field` (InputGroup + quick-pick chips),
  `choice-chip` (Toggle), `radio-row` (RadioGroup), `switch-row` (Switch), `text-field`
  (Field + Input), `pill-tabs` (Tabs), `status-pill` (Badge), plus `icons`, `logo`,
  `list-row`, `stat`, `notice`, `steps`, `eyebrow`, `section-heading`, `icon-tile`.
- `src/globals.css`: Inter and Crimson Pro, the Stark colour tokens (`brand`, `canvas`,
  `surface`, `paper`, `ink`, …) and the shadcn semantic variables mapped onto them.

## Adding or updating a shadcn component

From this folder:

```sh
bunx --bun shadcn@latest add <name>
```

Then, in the new file:

1. Swap `lucide-react` imports for Reicon, e.g.
   `import { ChevronDown as ChevronDownIcon } from "reicon-react"`. Stark uses Reicon only.
2. Restyle anything that clashes with the tokens above, then run `bun lint:fix` from the
   repo root.

If the CLI writes `import { cn } from "cn"` or adds a `cn` package, point the import at
`@stark/ui/utils/cn` and remove the package.
