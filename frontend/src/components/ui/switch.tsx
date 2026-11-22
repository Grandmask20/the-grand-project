"use client"

import * as React from "react"
import { Switch as SwitchPrimitive } from "radix-ui"

import { cn } from "@/utils/Cn"

function Switch({ className, ...props }: React.ComponentProps<typeof SwitchPrimitive.Root>) {
  return (
    <SwitchPrimitive.Root
      data-slot="switch"
      className={cn(
        // the game's options menu toggle: a ring, filled when on (Theme.css .poe-toggle)
        "poe-toggle peer inline-flex shrink-0 outline-none disabled:cursor-not-allowed disabled:opacity-50",
        className
      )}
      {...props}
    >
      <SwitchPrimitive.Thumb
        data-slot="switch-thumb"
        className="hidden"
      />
    </SwitchPrimitive.Root>
  )
}

export { Switch }
