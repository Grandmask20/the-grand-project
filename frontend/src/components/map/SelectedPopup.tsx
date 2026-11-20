import { XIcon } from "lucide-react";
import type { Map as MapLibreMap } from "maplibre-gl";
import { useEffect, useState } from "react";
import { SelectedBox } from "@/components/find/SelectedBox";
import type { Geo } from "@/logic/Geo";
import { useAppStore } from "@/store/AppStore";
import { cn } from "@/utils/Cn";

/** Under this many px from the map's top, the window opens below the spot instead of above it. */
const ROOM_ABOVE = 260;

/**
 * What is selected, in a window over the map where it was clicked (PO: an info window there, not a panel at the
 * side), following it as the map moves; off the view, it waits out of sight. It sits next to the map, not in it:
 * a click in it is the page's, not a click on the map under it.
 */
export function SelectedPopup({ map, geo }: { map: MapLibreMap; geo: Geo }) {
	const selected = useAppStore((s) => s.selected);
	const select = useAppStore((s) => s.select);
	const [at, setAt] = useState<{ x: number; y: number; w: number; h: number } | null>(null);
	const x = selected?.x;
	const y = selected?.y;

	useEffect(() => {
		if (x === undefined || y === undefined) return setAt(null);
		const place = () => {
			const p = map.project(geo.toLngLat(x, y));
			const c = map.getContainer();
			setAt({ x: p.x, y: p.y, w: c.clientWidth, h: c.clientHeight });
		};
		place();
		map.on("move", place);
		return () => {
			map.off("move", place);
		};
	}, [map, geo, x, y]);

	if (!selected || !at) return null;
	const out = at.x < 0 || at.y < 0 || (at.w > 0 && at.x > at.w) || (at.h > 0 && at.y > at.h);
	if (out) return null;
	const below = at.y < ROOM_ABOVE;
	return (
		<div
			className={cn("pointer-events-none absolute z-20 -translate-x-1/2", below ? "pt-4" : "-translate-y-full pb-4")}
			style={{ left: at.x, top: at.y }}
		>
			<section
				aria-label="Selected"
				className="pointer-events-auto relative w-[26rem] rounded-md border bg-card p-4 text-sm shadow-float"
			>
				<div className="mb-3 flex items-center justify-between">
					<h2 className="text-base font-semibold">Selected</h2>
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
				<SelectedBox />
				{/* the window's point, on the spot */}
				<span
					aria-hidden
					className={cn(
						"absolute left-1/2 size-3 -translate-x-1/2 rotate-45 border bg-card",
						below ? "-top-1.5 border-r-0 border-b-0" : "-bottom-1.5 border-t-0 border-l-0",
					)}
				/>
			</section>
		</div>
	);
}
