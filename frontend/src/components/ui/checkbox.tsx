"use client"

import * as React from "react"
import { Checkbox as CheckboxPrimitive } from "radix-ui"

import { cn } from "@/utils/Cn"

function Checkbox({ className, ...props }: React.ComponentProps<typeof CheckboxPrimitive.Root>) {
  return (
    <CheckboxPrimitive.Root
      data-slot="checkbox"
      className={cn(
        // the game's square checkbox (user: PoE's UI elements): its picture for unticked and ticked (Theme.css)
        "peer poe-check focus-visible:ring-ring/50 size-4 shrink-0 outline-none focus-visible:ring-[3px] disabled:cursor-not-allowed disabled:opacity-50",
        className
      )}
      {...props}
    >
 
    </CheckboxPrimitive.Root>
  )
}

export { Checkbox }
