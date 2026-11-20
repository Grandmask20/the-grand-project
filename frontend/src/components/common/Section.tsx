import { ChevronDownIcon, ChevronRightIcon } from "lucide-react";
import { type ReactNode, useState } from "react";
import { cn } from "@/utils/Cn";

/** A titled part of a side panel tab; `foldable`, its title folds it away and opens it again (View: PO, an accordion). */
export function Section({
	title,
	children,
	className,
	actions,
	locked = false,
	foldable = false,
	startOpen = true,
}: {
	title: string;
	children: ReactNode;
	className?: string;
	actions?: ReactNode;
	/** Shown greyed out and not usable (e.g. view settings while the timelapse is open). */
	locked?: boolean;
	foldable?: boolean;
	/** Foldable: open to begin with. */
	startOpen?: boolean;
}) {
	const [open, setOpen] = useState(startOpen);
	const shown = !foldable || open;
	const heading = <h3 className="text-xs font-semibold tracking-wide text-gold uppercase">{title}</h3>;
	return (
		<section className={cn("flex flex-col gap-2", className)} aria-disabled={locked || undefined}>
			<div className="flex items-center justify-between gap-2">
				{foldable ? (
					<button
						type="button"
						aria-expanded={open}
						onClick={() => setOpen(!open)}
						className="-mx-1 flex flex-1 items-center gap-1 rounded px-1 py-0.5 text-left hover:bg-accent/50"
					>
						{open ? (
							<ChevronDownIcon className="size-3.5 text-muted-foreground" aria-hidden />
						) : (
							<ChevronRightIcon className="size-3.5 text-muted-foreground" aria-hidden />
						)}
						{heading}
					</button>
				) : (
					heading
				)}
				{actions && shown && (
					// (locked with the rest: its buttons stayed usable, CodeRabbit)
					<div className={cn(locked && "pointer-events-none opacity-45")} inert={locked}>
						{actions}
					</div>
				)}
			</div>
			{shown && (
				<div className={cn("flex flex-col gap-2", locked && "pointer-events-none opacity-45")} inert={locked}>
					{children}
				</div>
			)}
		</section>
	);
}
