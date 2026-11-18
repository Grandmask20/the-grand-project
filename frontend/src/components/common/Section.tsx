import type { ReactNode } from "react";
import { cn } from "@/utils/Cn";

/** A titled part of a side panel tab. */
export function Section({
	title,
	children,
	className,
	actions,
	locked = false,
}: {
	title: string;
	children: ReactNode;
	className?: string;
	actions?: ReactNode;
	/** Shown greyed out and not usable (e.g. view settings while the timelapse is open). */
	locked?: boolean;
}) {
	return (
		<section className={cn("flex flex-col gap-2", className)} aria-disabled={locked || undefined}>
			<div className="flex items-center justify-between gap-2">
				<h3 className="text-xs font-semibold tracking-wide text-gold uppercase">{title}</h3>
				{actions && (
					// (locked with the rest: its buttons stayed usable, CodeRabbit)
					<div className={cn(locked && "pointer-events-none opacity-45")} inert={locked}>
						{actions}
					</div>
				)}
			</div>
			<div className={cn("flex flex-col gap-2", locked && "pointer-events-none opacity-45")} inert={locked}>
				{children}
			</div>
		</section>
	);
}
