import { XIcon } from "lucide-react";
import { SelectedBox } from "@/components/find/SelectedBox";
import { useSettings } from "@/hooks/app/UseSettings";
import { useAppStore } from "@/store/AppStore";

/**
 * What is selected, in a panel at the map's side (PO: not over the map; it was at the bottom of the Find tab, out of
 * view under the lists: user). Nothing selected: no panel, the map takes its room.
 */
export function InspectorPanel() {
	const selected = useAppStore((s) => !!s.selected);
	const select = useAppStore((s) => s.select);
	const side = useSettings()?.ui.side ?? "left"; // (the side panel's side: this one is across the map from it)
	if (!selected) return null;
	return (
		<aside
			aria-label="Selected"
			className={`flex w-72 shrink-0 flex-col bg-card ${side === "right" ? "border-r" : "border-l"}`}
		>
			<div className="flex items-center justify-between px-3 pt-3 pb-1">
				<h2 className="text-sm font-semibold">Selected</h2>
				<button
					type="button"
					aria-label="Close"
					title="Close"
					onClick={() => select(null)}
					className="rounded p-1 text-muted-foreground hover:bg-accent hover:text-foreground"
				>
					<XIcon className="size-4" />
				</button>
			</div>
			<div className="min-h-0 flex-1 overflow-y-auto px-3 pt-2 pb-4">
				<SelectedBox />
			</div>
		</aside>
	);
}
