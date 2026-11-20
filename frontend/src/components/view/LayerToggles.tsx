import { RouteIcon } from "lucide-react";
import { useSettings, useUpdateSettings } from "@/hooks/app/UseSettings";
import { cn } from "@/utils/Cn";

/** "Show on the map": one toggle per layer. Removed changes what the app puts in the tiles. */
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
	["Removed", "Removed"],
	["3D models", "3D models"],
	["Route", "Routes"], // (one button for the route shown and the saved ones: routesButton)
	["Debug marks", "Debug marks"],
];

export const OFF_BY_DEFAULT = new Set(["Doubtful", "Removed"]);

/** The Routes button (user): one press goes on (all) -> saved only (the bookmarked ones) -> off -> on. "Route" is the
 * route found or tracked, "Saved routes" the routes saved with the bookmarks. `state` / `short`: its words, whole and
 * for a narrow panel. */
export function routesButton(layers: Record<string, boolean>): {
	label: string;
	state: string;
	short: string;
	pressed: boolean | "mixed";
	next: Record<string, boolean>;
} {
	const route = layers.Route !== false;
	const saved = layers["Saved routes"] !== false;
	const out = (state: string, short: string, pressed: boolean | "mixed", next: Record<string, boolean>) => ({
		label: `Routes: ${state}`,
		state,
		short,
		pressed,
		next,
	});
	if (route) return out("on", "on", true, { Route: false, "Saved routes": true });
	if (saved) return out("saved only", "saved", "mixed", { Route: false, "Saved routes": false });
	return out("off", "off", false, { Route: true, "Saved routes": true });
}

/** The Routes button's words in its cell: "Routes: saved only" when it fits, "Routes: saved" narrower, the route
 * symbol and "saved" narrowest (user: it took two cells). The panel's width decides (a container query). */
export function RoutesLabel({ r }: { r: ReturnType<typeof routesButton> }) {
	return (
		<>
			<RouteIcon className="inline size-3.5 align-[-2px] @min-[21rem]:hidden" aria-hidden />
			<span className="hidden @min-[21rem]:inline">Routes: </span>
			<span className="@min-[27rem]:hidden">{r.short}</span>
			<span className="hidden @min-[27rem]:inline">{r.state}</span>
		</>
	);
}

export function LayerToggles() {
	const settings = useSettings();
	const update = useUpdateSettings();
	const layers = settings?.layers ?? {};
	return (
		<div className="@container grid grid-cols-3 gap-1">
			{LAYERS.map(([key, label]) => {
				if (key === "Route") {
					const r = routesButton(layers);
					return (
						<button
							key={key}
							type="button"
							aria-pressed={r.pressed}
							aria-label={r.label}
							title={r.label}
							onClick={() => update.mutate({ layers: r.next })}
							className={cn(
								"truncate rounded border px-1.5 py-1 text-xs",
								r.pressed ? "border-gold/70 bg-accent text-foreground" : "text-muted-foreground hover:bg-accent/50",
							)}
						>
							<RoutesLabel r={r} />
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
