import { Button as ButtonPrimitive } from "@base-ui/react/button";
import { cn } from "@stark/ui/utils/cn";
import { cva, type VariantProps } from "class-variance-authority";

// shadcn's button, styled the Stark way: burnt orange for the main action.
// The shape comes from --radius-control: the dashboard sets an 8px rectangle, the
// website leaves it unset and keeps its pills. `light`, `ink` and `paper` are the
// website's additions.
const buttonVariants = cva(
  "group/button inline-flex shrink-0 cursor-pointer items-center justify-center gap-1.5 rounded-[var(--radius-control,9999px)] border border-transparent bg-clip-padding font-medium whitespace-nowrap no-underline transition-all outline-none select-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 active:not-aria-[haspopup]:translate-y-px disabled:pointer-events-none disabled:opacity-50 aria-invalid:border-destructive aria-invalid:ring-3 aria-invalid:ring-destructive/20 [&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-4",
  {
    variants: {
      variant: {
        default: "bg-primary text-primary-foreground hover:bg-primary/90",
        brand: "bg-brand text-white hover:bg-[#d04a12]",
        outline:
          "border-border bg-background shadow-control hover:bg-muted hover:text-foreground aria-expanded:bg-muted aria-expanded:text-foreground dark:border-input dark:bg-input/30 dark:hover:bg-input/50",
        secondary:
          "border-border bg-card text-foreground shadow-control hover:bg-muted aria-expanded:bg-muted dark:bg-secondary dark:hover:bg-accent",
        ghost:
          "bg-transparent text-fg-2 hover:bg-muted hover:text-foreground aria-expanded:bg-muted aria-expanded:text-foreground",
        destructive:
          "bg-destructive/10 text-destructive hover:bg-destructive/20 focus-visible:border-destructive/40 focus-visible:ring-destructive/20",
        link: "text-primary underline-offset-4 hover:underline",
        light: "bg-fg text-canvas-deep hover:bg-white",
        ink: "bg-ink text-white hover:bg-black",
        paper: "bg-paper-2 text-ink hover:bg-[#dedad0]",
      },
      size: {
        default: "min-h-9 px-3.5 text-[13px]",
        xs: "min-h-6 gap-1 px-2 text-xs [&_svg:not([class*='size-'])]:size-3",
        sm: "min-h-8 gap-1 px-3 text-[13px] [&_svg:not([class*='size-'])]:size-3.5",
        md: "min-h-11 px-5 text-sm",
        lg: "min-h-10 px-4 text-sm",
        icon: "size-9",
        "icon-xs": "size-6 [&_svg:not([class*='size-'])]:size-3",
        "icon-sm": "size-8",
        "icon-lg": "size-10",
      },
      block: {
        true: "w-full",
      },
    },
    defaultVariants: {
      variant: "default",
      size: "default",
    },
  },
);

function Button({
  className,
  variant = "default",
  size = "default",
  block,
  ...props
}: ButtonPrimitive.Props & VariantProps<typeof buttonVariants>) {
  return (
    <ButtonPrimitive
      data-slot="button"
      className={cn(buttonVariants({ variant, size, block, className }))}
      {...props}
    />
  );
}

export { Button, buttonVariants };
