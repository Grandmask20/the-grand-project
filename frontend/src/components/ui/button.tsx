import * as React from "react"
import { Slot as SlotPrimitive } from "radix-ui"
import { cva, type VariantProps } from "class-variance-authority"

import { cn } from "@/utils/Cn"

const buttonVariants = cva(
  "inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-md text-sm font-medium transition-all disabled:pointer-events-none disabled:opacity-50 [&_svg]:pointer-events-none [&_svg:not([class*='size-'])]:size-4 shrink-0 [&_svg]:shrink-0 outline-none focus-visible:border-ring focus-visible:ring-ring/50 focus-visible:ring-[3px] aria-invalid:ring-destructive/20 aria-invalid:border-destructive",
  {
    variants: {
      variant: {
        // the game's buttons (Theme.css .poe-btn): green for what is on or confirms, grey for the rest, red for
        // deleting; an icon alone gets the game's square framed button (the sizes below)
        default: "poe-btn poe-btn-green",
        destructive: "poe-btn poe-btn-red focus-visible:ring-destructive/20",
        outline: "poe-btn",
        secondary: "poe-btn",
        ghost: "hover:bg-accent hover:text-accent-foreground",
        link: "text-gold underline-offset-4 hover:underline",
      },
      size: {
        default: "h-9 px-4 py-2 has-[>svg]:px-3",
        sm: "h-8 rounded-md gap-1.5 px-3 has-[>svg]:px-2.5",
        xs: "h-7 rounded-md gap-1 px-2 text-xs has-[>svg]:px-1.5 poe-btn-xs",
        lg: "h-10 rounded-md px-6 has-[>svg]:px-4 poe-btn-lg",
        icon: "size-9 poe-icon-btn",
        "icon-sm": "size-7 poe-icon-btn",
      },
    },
    defaultVariants: {
      variant: "default",
      size: "default",
    },
  }
)

function Button({
  className,
  variant,
  size,
  asChild = false,
  ...props
}: React.ComponentProps<"button"> &
  VariantProps<typeof buttonVariants> & {
    asChild?: boolean
  }) {
  const Comp = asChild ? SlotPrimitive.Slot : "button"

  return (
    <Comp
      data-slot="button"
      className={cn(buttonVariants({ variant, size, className }))}
      {...props}
    />
  )
}

export { Button, buttonVariants }
