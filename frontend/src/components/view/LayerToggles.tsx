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
	["Route", "Routes"], // (one button for the route shown and the saved ones: routesButton)
	["Debug marks", "Debug marks"],
];

export const OFF_BY_DEFAULT = new Set(["Doubtful", "Removed"]);

/** The Routes button (user): one press goes on -> saved only -> off -> on. "Route" is the route found or tracked,
 * "Saved routes" the routes saved with the bookmarks. */
export function routesButton(layers: Record<string, boolean>): {
	label: string;
	pressed: boolean | "mixed";
	next: Record<string, boolean>;
} {
	const route = layers.Route !== false;
	const saved = layers["Saved routes"] !== false;
	if (route) return { label: "Routes: on", pressed: true, next: { Route: false, "Saved routes": true } };
	if (saved) return { label: "Routes: saved only", pressed: "mixed", next: { Route: false, "Saved routes": false } };
	return { label: "Routes: off", pressed: false, next: { Route: true, "Saved routes": true } };
}

export function LayerToggles() {
	const settings = useSettings();
	const update = useUpdateSettings();
	const layers = settings?.layers ?? {};
	return (
		<div className="grid grid-cols-3 gap-1">
			{LAYERS.map(([key, label]) => {
				if (key === "Route") {
					const r = routesButton(layers);
					return (
						<button
							key={key}
							type="button"
							aria-pressed={r.pressed}
							onClick={() => update.mutate({ layers: r.next })}
							className={cn(
								"col-span-2 rounded border px-1.5 py-1 text-xs",
								r.pressed ? "border-gold/70 bg-accent text-foreground" : "text-muted-foreground hover:bg-accent/50",
							)}
						>
							{r.label}
						</button>
					);
				}
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
