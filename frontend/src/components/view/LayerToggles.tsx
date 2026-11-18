import { useSettings, useUpdateSettings } from "@/hooks/app/UseSettings";
import { cn } from "@/utils/Cn";

/** "Show on the map": one toggle per layer. Doubtful and Removed change what the app puts in the tiles. */
export const LAYERS: [string, string][] = [
	["Terrain", "Ground"],
	["Paths", "Paths"],
	["Nodes", "Maps"],
	["Icons", "Icons"],
	["Landmarks", "Landmarks"],
	["Bookmarks", "Bookmarks"],
	["Labels", "Names"],
	["City & stronghold biomes", "Biomes"],
	["Recent additions", "Recent"],
	["Doubtful", "Doubtful"],
	["Removed", "Removed"],
	["3D models", "3D models"],
	["Route", "Route"],
	["Debug marks", "Debug marks"],
];

const OFF_BY_DEFAULT = new Set(["Doubtful", "Removed"]);

export function LayerToggles() {
	const settings = useSettings();
	const update = useUpdateSettings();
	const layers = settings?.layers ?? {};
	return (
		<div className="grid grid-cols-3 gap-1">
			{LAYERS.map(([key, label]) => {
				const on = layers[key] ?? !OFF_BY_DEFAULT.has(key);
				return (
					<button
						key={key}
						type="button"
						aria-pressed={on}
						onClick={() => update.mutate({ layers: { [key]: !on } })}
						className={cn(
							"rounded border px-1.5 py-1 text-xs",
							on ? "border-gold/70 bg-accent text-foreground" : "text-muted-foreground hover:bg-accent/50",
						)}
					>
						{label}
					</button>
				);
			})}
		</div>
	);
}
