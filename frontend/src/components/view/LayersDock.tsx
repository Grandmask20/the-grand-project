import { useMeta } from "@/hooks/app/UseMeta";
import { useSettings, useUpdateSettings } from "@/hooks/app/UseSettings";
import { cityColours, styleColour } from "@/logic/Colours";
import { useAppStore } from "@/store/AppStore";
import { cn } from "@/utils/Cn";
import { LAYERS, OFF_BY_DEFAULT, RoutesLabel, routesButton } from "./LayerToggles";

/** Layers only the 3D view uses: listed while the map is tilted (user). */
const ONLY_3D = new Set(["3D models"]);

/**
 * "Layers" at the bottom of the side panel, always in view as in the old window (user: the View tab hid
 * it), with the colour legend that was the old window's bottom bar. Folds away to one line.
 */
export function LayersDock() {
	const meta = useMeta().data;
	const settings = useSettings();
	const update = useUpdateSettings();
	const tilted = useAppStore((s) => (s.camera?.pitch ?? 0) > 1);
	const recording = useAppStore((s) => !!s.replay?.recording); // the layers stay as recorded
	// folded by default, and remembered across reloads (user)
	const open = !!settings?.ui.layers_open;
	const setOpen = (v: boolean) => update.mutate({ ui: { layers_open: v } });
	if (!settings || !meta) return null;
	const layers = settings.layers ?? {};
	const st = settings.style;
	const shown = LAYERS.filter(([key]) => tilted || !ONLY_3D.has(key));

	const legend: [string, string][] = [
		["map: 2+ shots / icon", styleColour(st, "map_col", meta.colours.node.confirmed)],
		["map: 1 shot", meta.colours.node.single],
		...Object.entries(meta.colours.node_state).map(([k, c]) => [`map: ${k}`, c] as [string, string]),
		["path", styleColour(st, "path_col", meta.colours.path_multi)],
		["path: 1 shot", styleColour(st, "path_col1", meta.colours.path_single)],
		["abyss chain", meta.colours.path_abyss],
		...Object.entries(cityColours(meta, st)).map(([k, c]) => [`near ${k}`, c] as [string, string]),
	];

	return (
		<section
			className="@container shrink-0 border-t border-[var(--tab-edge)] bg-black/30 px-3 py-2"
			aria-label="Layers"
		>
			<button
				type="button"
				className="flex w-full items-center justify-between text-xs font-semibold tracking-wide text-gold uppercase"
				onClick={() => setOpen(!open)}
				aria-expanded={open}
			>
				Layers
				{/* the game's dropdown button, turned while open */}
				<span className={cn("poe-drop", !open && "rotate-180")} aria-hidden="true" />
			</button>
			{open && (
				<>
					{/* toggle buttons: lit when shown (user: this layout reads better than checkboxes) */}
					<div className="mt-1.5 grid grid-cols-3 gap-1.5">
						{shown.map(([key, label]) => {
							if (key === "Route") {
								// on -> saved only -> off (user: the saved routes had no switch)
								const r = routesButton(layers);
								return (
									<button
										key={key}
										type="button"
										aria-pressed={r.pressed}
										aria-label={r.label}
										title={r.label}
										disabled={recording}
										onClick={() => update.mutate({ layers: r.next })}
										// the game's buttons (user): green on, red when off (any "off" is red: user)
										className={cn("poe-btn poe-btn-xs truncate", r.pressed ? "poe-btn-green" : "poe-btn-red")}
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
									disabled={recording}
									onClick={() => update.mutate({ layers: { [key]: !on } })}
									// the game's buttons (user): green on, grey off
									className={cn("poe-btn poe-btn-xs truncate", on ? "poe-btn-green" : "text-[#bfb08a]")}
								>
									{label}
								</button>
							);
						})}
					</div>
					<div className="mt-1.5 flex flex-wrap gap-x-3 gap-y-0.5 border-t pt-1.5">
						{legend.map(([label, colour]) => (
							<span key={label} className="flex items-center gap-1 text-[11px] text-muted-foreground">
								<span className="size-2.5 rounded-full" style={{ background: colour }} />
								{label}
							</span>
						))}
					</div>
				</>
			)}
		</section>
	);
}
