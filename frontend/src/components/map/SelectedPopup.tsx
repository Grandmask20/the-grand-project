import { XIcon } from "lucide-react";
import type { Map as MapLibreMap } from "maplibre-gl";
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { SelectedBox } from "@/components/find/SelectedBox";
import type { Geo } from "@/logic/Geo";
import { useAppStore } from "@/store/AppStore";
import { cn } from "@/utils/Cn";

/** The window's width before it is measured (w-[26rem]). */
const WIDTH = 416;
/** Room kept between the window and the map's edges, px. */
const EDGE = 8;
/** The gap the window's point takes between the spot and the window, px. */
const GAP = 16;
/** The point stays this far in from the window's corners, px. */
const POINT_IN = 20;

/** Where the window goes for a spot on the map: its left, above or below, the most height it has, and where its point
 * sits on it. Exported for its test.
 *
 * Args: the spot (x, y), the map's size (w, h) and the window's size (cw: its width; ch: the height its content wants).
 */
export function placeWindow(x: number, y: number, w: number, h: number, cw: number, ch: number) {
	// across: centred on the spot, moved in from an edge it would cross (CodeRabbit: its Close button went off)
	const left = Math.max(EDGE, Math.min(x - cw / 2, w - cw - EDGE));
	const point = Math.max(POINT_IN, Math.min(x - left, cw - POINT_IN));
	// up or down: above when it fits there, else below when it fits there, else where there is more room, the window
	// then as tall as that room with its content scrolling (CodeRabbit: a tall window went over the top)
	const above = y - GAP - EDGE;
	const under = h - y - GAP - EDGE;
	const below = !(ch <= above) && (ch <= under || under > above);
	return { left, point, below, maxHeight: Math.max(120, below ? under : above) };
}

/**
 * What is selected, in a window over the map where it was clicked (PO: an info window there, not a panel at the
 * side), following it as the map moves; off the view, it waits out of sight. It sits next to the map, not in it:
 * a click in it is the page's, not a click on the map under it.
 */
export function SelectedPopup({ map, geo }: { map: MapLibreMap; geo: Geo }) {
	const selected = useAppStore((s) => s.selected);
	const select = useAppStore((s) => s.select);
	const [at, setAt] = useState<{ x: number; y: number; w: number; h: number } | null>(null);
	const [size, setSize] = useState({ w: WIDTH, h: 0 });
	const card = useRef<HTMLElement>(null);
	const body = useRef<HTMLDivElement>(null);
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

	// the window's size: its width, and the height its content wants (also while it scrolls), measured again as its
	// content changes (the map icons come later)
	const shown = !!selected && !!at;
	useLayoutEffect(() => {
		const c = card.current;
		const b = body.current;
		if (!shown || !c || !b) return;
		const measure = () => {
			const w = c.offsetWidth || WIDTH;
			const h = c.offsetHeight - b.clientHeight + b.scrollHeight;
			setSize((s) => (s.w === w && s.h === h ? s : { w, h }));
		};
		measure();
		const ro = new ResizeObserver(measure);
		ro.observe(c);
		if (b.firstElementChild) ro.observe(b.firstElementChild);
		return () => ro.disconnect();
	}, [shown]);

	// another selection starts at its top (CodeRabbit: the last one's scroll hid the new title); the same one's
	// data refreshing keeps its scroll
	const who = selected ? `${selected.kind}:${selected.id}` : null;
	useEffect(() => {
		if (who && body.current) body.current.scrollTop = 0;
	}, [who]);

	if (!selected || !at) return null;
	const out = at.x < 0 || at.y < 0 || (at.w > 0 && at.x > at.w) || (at.h > 0 && at.y > at.h);
	if (out) return null;
	const { left, point, below, maxHeight } = placeWindow(at.x, at.y, at.w || Infinity, at.h || Infinity, size.w, size.h);
	return (
		<div
			className={cn("pointer-events-none absolute z-20", below ? "pt-4" : "-translate-y-full pb-4")}
			style={{ left, top: at.y }}
		>
			<section
				ref={card}
				aria-label="Selected"
				className="pointer-events-auto relative flex w-[26rem] flex-col rounded-md border bg-card text-sm shadow-float"
				style={{ maxHeight }}
			>
				<div className="flex items-center justify-between px-4 pt-4 pb-3">
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
				<div ref={body} data-testid="selected-body" className="min-h-0 overflow-y-auto px-4 pb-4">
					<div>
						<SelectedBox />
					</div>
				</div>
				{/* the window's point, on the spot */}
				<span
					aria-hidden
					data-testid="selected-point"
					className={cn(
						"absolute size-3 -translate-x-1/2 rotate-45 border bg-card",
						below ? "-top-1.5 border-r-0 border-b-0" : "-bottom-1.5 border-t-0 border-l-0",
					)}
					style={{ left: point }}
				/>
			</section>
		</div>
	);
}
