"use client";

import { Tooltip as TooltipPrimitive } from "@base-ui/react/tooltip";

type TooltipPayload = {
  content: React.ReactNode;
  side: TooltipPrimitive.Positioner.Props["side"];
};

const tooltipHandle = TooltipPrimitive.createHandle<TooltipPayload>();

function TooltipProvider({ delay = 50, children, ...props }: TooltipPrimitive.Provider.Props) {
  return (
    <TooltipPrimitive.Provider data-slot="tooltip-provider" delay={delay} {...props}>
      {children}
      <TooltipPrimitive.Root handle={tooltipHandle}>
        {({ payload }) =>
          payload && (
            <TooltipPrimitive.Portal>
              <TooltipPrimitive.Positioner
                side={payload.side}
                sideOffset={6}
                className="isolate z-50 h-(--positioner-height) w-(--positioner-width) max-w-(--available-width) transition-[top,left,right,bottom,transform] duration-200 ease-out data-instant:transition-none motion-reduce:transition-none"
              >
                <TooltipPrimitive.Popup
                  data-slot="tooltip-content"
                  className="relative h-(--popup-height,auto) min-h-6 w-(--popup-width,auto) max-w-xs overflow-clip rounded-md bg-foreground text-xs font-medium whitespace-nowrap text-background shadow-md transition-[width,height,opacity,filter] duration-200 ease-out data-ending-style:opacity-0 data-ending-style:blur-xs data-instant:transition-none data-starting-style:opacity-0 data-starting-style:blur-sm motion-reduce:transition-none"
                >
                  <TooltipPrimitive.Viewport className="**:data-current:px-2 **:data-current:py-1 **:data-current:transition-opacity **:data-current:duration-200 **:data-previous:px-2 **:data-previous:py-1 **:data-previous:transition-opacity **:data-previous:duration-200 **:data-current:data-starting-style:opacity-0 **:data-previous:data-ending-style:opacity-0">
                    {payload.content}
                  </TooltipPrimitive.Viewport>
                </TooltipPrimitive.Popup>
              </TooltipPrimitive.Positioner>
            </TooltipPrimitive.Portal>
          )
        }
      </TooltipPrimitive.Root>
    </TooltipPrimitive.Provider>
  );
}

function TooltipTrigger({
  content,
  side = "top",
  ...props
}: Omit<TooltipPrimitive.Trigger.Props<TooltipPayload>, "handle" | "payload"> &
  Pick<TooltipPayload, "content"> &
  Partial<Pick<TooltipPayload, "side">>) {
  return (
    <TooltipPrimitive.Trigger
      data-slot="tooltip-trigger"
      handle={tooltipHandle}
      payload={{ content, side }}
      {...props}
    />
  );
}

export { TooltipProvider, TooltipTrigger };
