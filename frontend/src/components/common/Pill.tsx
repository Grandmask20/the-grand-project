import type { ReactNode } from "react";
import { cn } from "@/utils/Cn";

/** A switch drawn as a pill (PO's canvas: Find's filters): lit gold when on. */
export function Pill({
	on,
	onClick,
	label,
	title,
	disabled,
	children,
}: {
	on: boolean;
	onClick: () => void;
	/** Its whole name, when the pill's words are short. */
	label?: string;
	title?: string;
	disabled?: boolean;
	children: ReactNode;
}) {
	return (
		<button
			type="button"
			aria-pressed={on}
			aria-label={label}
			title={title ?? label}
			disabled={disabled}
			onClick={onClick}
			className={cn(
				"h-7 rounded-full border px-3 text-xs font-medium whitespace-nowrap disabled:opacity-45",
				on
					? "border-gold/50 bg-gold/15 text-gold"
					: "border-border text-muted-foreground hover:bg-accent/50 hover:text-foreground",
			)}
		>
			{children}
		</button>
	);
}
