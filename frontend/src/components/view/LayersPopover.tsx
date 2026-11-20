import { LayersIcon } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useMeta } from "@/hooks/app/UseMeta";
import { useSettings, useUpdateSettings } from "@/hooks/app/UseSettings";
import { cityColours, styleColour } from "@/logic/Colours";
import { useAppStore } from "@/store/AppStore";
import { cn } from "@/utils/Cn";
import { LAYERS, OFF_BY_DEFAULT, RoutesLabel, routesButton } from "./LayerToggles";

/** Layers only the 3D view uses: listed while the map is tilted (user). */
const ONLY_3D = new Set(["3D models"]);

/** A layer's switch: lit when shown (user: this layout reads better than checkboxes). */
const pill = (on: boolean | "mixed") =>
	cn(
		"truncate rounded-full border px-2.5 py-1 text-xs",
		on ? "border-gold/70 bg-accent text-foreground" : "border-border text-muted-foreground hover:bg-accent/50",
	);

/**
 * "Show on the map": the Layers button of the status line and its switches over it, with the colour legend (PO: no
 * button over the map; it was the side panel's folding Layers dock). A click outside, or Esc, closes it.
 */
export function LayersPopover() {
	const meta = useMeta().data;
	const settings = useSettings();
	const update = useUpdateSettings();
	const tilted = useAppStore((s) => (s.camera?.pitch ?? 0) > 1);
	const recording = useAppStore((s) => !!s.replay?.recording); // the layers stay as recorded
	const [open, setOpen] = useState(false);
	const box = useRef<HTMLDivElement>(null);
	const trigger = useRef<HTMLButtonElement>(null);

	useEffect(() => {
		if (!open) return;
		const away = (e: PointerEvent) => {
			if (!box.current?.contains(e.target as Node)) setOpen(false);
		};
		// Esc closes it and goes no further: caught first (capture), it neither ends a map tool nor empties Find, and the
		// focus goes back to the Layers button (CodeRabbit). A click elsewhere leaves the focus where it went
		const esc = (e: KeyboardEvent) => {
			if (e.key !== "Escape") return;
			e.stopPropagation();
			setOpen(false);
			trigger.current?.focus();
		};
		window.addEventListener("pointerdown", away, true);
		window.addEventListener("keydown", esc, true);
		return () => {
			window.removeEventListener("pointerdown", away, true);
			window.removeEventListener("keydown", esc, true);
		};
	}, [open]);

	const layers = settings?.layers ?? {};
	const st = settings?.style;
	const shown = LAYERS.filter(([key]) => tilted || !ONLY_3D.has(key));
	const legend: [string, string][] =
		meta && st
			? [
					["map: 2+ shots / icon", styleColour(st, "map_col", meta.colours.node.confirmed)],
					["map: 1 shot", meta.colours.node.single],
					["path", styleColour(st, "path_col", meta.colours.path_multi)],
					["path: 1 shot", styleColour(st, "path_col1", meta.colours.path_single)],
					["abyss chain", meta.colours.path_abyss],
					...Object.entries(cityColours(meta, st)).map(([k, c]) => [`near ${k}`, c] as [string, string]),
				]
			: [];

	return (
		<div ref={box} className="relative">
			<button
				ref={trigger}
				type="button"
				aria-expanded={open}
				aria-haspopup="dialog"
				disabled={!settings || !meta}
				onClick={() => setOpen(!open)}
				className={cn(
					"flex h-6 items-center gap-1.5 rounded px-2 disabled:opacity-40",
					open ? "bg-gold text-background" : "hover:bg-accent hover:text-foreground",
				)}
			>
				<LayersIcon className="size-3.5" aria-hidden />
				Layers
			</button>
			{open && (
				<section
					role="dialog"
					aria-label="Show on the map"
					className="@container absolute right-0 bottom-full z-40 mb-2 w-80 rounded-md border bg-card p-3 font-sans shadow-float"
				>
					<h3 className="mb-2 text-xs font-semibold tracking-wide text-gold uppercase">Show on the map</h3>
					<div className="flex flex-wrap gap-1.5">
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
										className={pill(r.pressed)}
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
									className={pill(on)}
								>
									{label}
								</button>
							);
						})}
					</div>
					<div className="mt-3 flex flex-wrap gap-x-3 gap-y-0.5 border-t pt-2">
						{legend.map(([label, colour]) => (
							<span key={label} className="flex items-center gap-1 text-xs text-muted-foreground">
								<span className="size-2.5 rounded-full" style={{ background: colour }} />
								{label}
							</span>
						))}
					</div>
				</section>
			)}
		</div>
	);
}
