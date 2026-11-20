import { ChevronDownIcon, ChevronRightIcon } from "lucide-react";
import { type ReactNode, useState } from "react";
import { cn } from "@/utils/Cn";

/**
 * A titled part of a side panel tab. `foldable`: a row of an accordion (View: PO), its title folds it away and opens
 * it again, and folded it shows its `summary` (what is set in it). Open or not is its own, or `open` / `onToggle`
 * when kept elsewhere (the View tab keeps it while closed).
 */
export function Section({
	title,
	children,
	className,
	actions,
	locked = false,
	foldable = false,
	summary,
	open,
	onToggle,
}: {
	title: string;
	children: ReactNode;
	className?: string;
	actions?: ReactNode;
	/** Shown greyed out and not usable (e.g. view settings while the timelapse is open). */
	locked?: boolean;
	foldable?: boolean;
	summary?: string;
	open?: boolean;
	onToggle?: () => void;
}) {
	const [own, setOwn] = useState(true);
	const isOpen = open ?? own;
	const toggle = onToggle ?? (() => setOwn(!own));
	const body = (
		<div className={cn("flex flex-col gap-2", locked && "pointer-events-none opacity-45")} inert={locked}>
			{children}
		</div>
	);
	// (locked with the rest: its buttons stayed usable, CodeRabbit)
	const extra = actions && (
		<div className={cn(locked && "pointer-events-none opacity-45")} inert={locked}>
			{actions}
		</div>
	);

	if (foldable) {
		const Chevron = isOpen ? ChevronDownIcon : ChevronRightIcon;
		return (
			<section className={cn("border-b", className)} aria-disabled={locked || undefined}>
				<div className="flex items-center gap-2">
					<h3 className="min-w-0 flex-1">
						<button
							type="button"
							aria-expanded={isOpen}
							onClick={toggle}
							className="flex h-10 w-full items-center gap-2 text-left text-sm font-semibold hover:text-gold"
						>
							<Chevron className="size-4 shrink-0 text-muted-foreground" aria-hidden />
							<span className="shrink-0">{title}</span>
							{!isOpen && summary && (
								<span className="ml-auto truncate text-xs font-normal text-muted-foreground">{summary}</span>
							)}
						</button>
					</h3>
					{isOpen && extra}
				</div>
				{isOpen && <div className="pb-4 pl-6">{body}</div>}
			</section>
		);
	}

	return (
		<section className={cn("flex flex-col gap-2", className)} aria-disabled={locked || undefined}>
			<div className="flex items-center justify-between gap-2">
				<h3 className="text-xs font-semibold tracking-wide text-gold uppercase">{title}</h3>
				{extra}
			</div>
			{body}
		</section>
	);
}
