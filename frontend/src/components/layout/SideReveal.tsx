import { useSettings, useUpdateSettings } from "@/hooks/app/UseSettings";
import { cn } from "@/utils/Cn";

/**
 * Hides or shows the side panel (user's notes: a hideable sidebar), with the game's half-round collapse button (its
 * cosmetics panel's): its flat side on the panel's edge while it shows, on the map's edge while hidden, its dome
 * towards the map. Remembered for every atlas.
 */
export function SideReveal({ className }: { className?: string }) {
	const settings = useSettings();
	const update = useUpdateSettings();
	const hidden = !!settings?.ui.side_hidden;
	const left = (settings?.ui.side ?? "left") === "left";
	// (the dome points up: turned towards the map, right of a panel on the left, left of one on the right)
	return (
		<button
			type="button"
			aria-label={hidden ? "Show the side panel" : "Hide the side panel"}
			title={hidden ? "Show the side panel" : "Hide the side panel"}
			aria-pressed={!hidden}
			onClick={() => update.mutate({ ui: { side_hidden: !hidden } })}
			className={cn("poe-reveal-side", left ? "rotate-90" : "-rotate-90", className)}
		/>
	);
}
