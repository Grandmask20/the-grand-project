import { ChevronDownIcon, ChevronUpIcon } from "lucide-react";
import { useState } from "react";
import { useMeta } from "@/hooks/app/UseMeta";
import { useSettings, useUpdateSettings } from "@/hooks/app/UseSettings";
import { cityColours, styleColour } from "@/logic/Colours";
import { useAppStore } from "@/store/AppStore";
import { LAYERS, OFF_BY_DEFAULT } from "./LayerToggles";

/** Layers only the 3D view uses: listed while the map is tilted (user). */
const ONLY_3D = new Set(["3D models"]);

/**
 * "Show on the map" at the bottom of the side panel, always in view as in the old window (user: the View tab hid
 * it), with the colour legend that was the old window's bottom bar. Folds away to one line.
 */
export function LayersDock() {
	const meta = useMeta().data;
	const settings = useSettings();
	const update = useUpdateSettings();
	const tilted = useAppStore((s) => (s.camera?.pitch ?? 0) > 1);
	const [open, setOpen] = useState(true);
	if (!settings || !meta) return null;
	const layers = settings.layers ?? {};
	const st = settings.style;
	const shown = LAYERS.filter(([key]) => tilted || !ONLY_3D.has(key));

	const legend: [string, string][] = [
		["map: 2+ shots / icon", styleColour(st, "map_col", meta.colours.node.confirmed)],
		["map: 1 shot", meta.colours.node.single],
		["path", styleColour(st, "path_col", meta.colours.path_multi)],
		["path: 1 shot", styleColour(st, "path_col1", meta.colours.path_single)],
		["abyss chain", meta.colours.path_abyss],
		...Object.entries(cityColours(meta, st)).map(([k, c]) => [`near ${k}`, c] as [string, string]),
	];

	return (
		<section className="shrink-0 border-t bg-card/60 px-3 py-2" aria-label="Show on the map">
			<button
				type="button"
				className="flex w-full items-center justify-between text-xs font-semibold tracking-wide text-gold uppercase"
				onClick={() => setOpen(!open)}
				aria-expanded={open}
			>
				Show on the map
				{open ? <ChevronDownIcon className="size-4" /> : <ChevronUpIcon className="size-4" />}
			</button>
			{open && (
				<>
					<div className="mt-1.5 grid grid-cols-3 gap-x-2 gap-y-0.5">
						{shown.map(([key, label]) => {
							const on = layers[key] ?? !OFF_BY_DEFAULT.has(key);
							return (
								<label key={key} className="flex cursor-pointer items-center gap-1.5 truncate py-0.5 text-xs">
									<input
										type="checkbox"
										className="accent-[var(--color-gold)]"
										checked={on}
										onChange={() => update.mutate({ layers: { [key]: !on } })}
									/>
									<span className={on ? "" : "text-muted-foreground"}>{label}</span>
								</label>
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
