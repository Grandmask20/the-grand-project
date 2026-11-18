import type { ReactNode } from "react";
import { cn } from "@/utils/Cn";

/** A titled part of a side panel tab. */
export function Section({
	title,
	children,
	className,
	actions,
}: {
	title: string;
	children: ReactNode;
	className?: string;
	actions?: ReactNode;
}) {
	return (
		<section className={cn("flex flex-col gap-2", className)}>
			<div className="flex items-center justify-between gap-2">
				<h3 className="text-xs font-semibold tracking-wide text-gold uppercase">{title}</h3>
				{actions}
			</div>
			{children}
		</section>
	);
}
