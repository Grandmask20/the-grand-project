import { XIcon } from "lucide-react";
import type { Map as MapLibreMap } from "maplibre-gl";
import { useCallback, useEffect, useRef, useState } from "react";
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

/** The side of the window its point is on: under it (the window above the spot), over it, or at its left / right. */
export type PointSide = "bottom" | "top" | "left" | "right";

/** Where the window goes for a spot on the map, all of it in view and never scrolling (user): above the spot, else
 * below it, else beside it (as high as the map lets it, its point still on the spot); across, centred on the spot and
 * moved in from an edge it would cross (CodeRabbit: its Close button went off). Exported for its test.
 *
 * Args: the spot (x, y), the map's size (w, h) and the window's (cw, ch).
 *
 * Returns: its top left, the side its point is on, and where along that side.
 */
export function placeWindow(x: number, y: number, w: number, h: number, cw: number, ch: number) {
	const clamp = (v: number, lo: number, hi: number) => Math.max(lo, Math.min(v, hi));
	if (ch + GAP + EDGE <= y || ch + GAP + EDGE <= h - y) {
		const above = ch + GAP + EDGE <= y;
		const left = clamp(x - cw / 2, EDGE, w - cw - EDGE);
		return {
			left,
			top: above ? y - GAP - ch : y + GAP,
			side: (above ? "bottom" : "top") as PointSide,
			point: clamp(x - left, POINT_IN, cw - POINT_IN),
		};
	}
	const right = x + GAP + cw + EDGE <= w || x < w / 2;
	const top = clamp(y - ch / 2, EDGE, h - ch - EDGE);
	return {
		left: right ? x + GAP : Math.max(EDGE, x - GAP - cw),
		top: Math.max(EDGE, top),
		side: (right ? "left" : "right") as PointSide,
		point: clamp(y - Math.max(EDGE, top), POINT_IN, ch - POINT_IN),
	};
}

/** The point's corner of a turned square, by the side it sits on. */
const POINT: Record<PointSide, string> = {
	bottom: "-bottom-1.5 -translate-x-1/2 border-t-0 border-l-0",
	top: "-top-1.5 -translate-x-1/2 border-r-0 border-b-0",
	left: "-left-1.5 -translate-y-1/2 border-t-0 border-r-0",
	right: "-right-1.5 -translate-y-1/2 border-b-0 border-l-0",
};

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

	// the window's size, measured as it comes into view (also after waiting out of sight: CodeRabbit) and again as its
	// content changes (the map icons come later)
	const watch = useRef<ResizeObserver | null>(null);
	const card = useCallback((el: HTMLElement | null) => {
		watch.current?.disconnect();
		watch.current = null;
		if (!el) return;
		const measure = () => {
			const w = el.offsetWidth || WIDTH;
			const h = el.offsetHeight;
			setSize((s) => (s.w === w && s.h === h ? s : { w, h }));
		};
		measure();
		watch.current = new ResizeObserver(measure);
		watch.current.observe(el);
	}, []);

	if (!selected || !at) return null;
	const out = at.x < 0 || at.y < 0 || (at.w > 0 && at.x > at.w) || (at.h > 0 && at.y > at.h);
	if (out) return null;
	const { left, top, side, point } = placeWindow(at.x, at.y, at.w || Infinity, at.h || Infinity, size.w, size.h);
	return (
		<section
			ref={card}
			aria-label="Selected"
			className="absolute z-20 w-[26rem] rounded-md border bg-card p-4 text-sm shadow-float"
			style={{ left, top }}
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
				data-testid="selected-point"
				className={cn("absolute size-3 rotate-45 border bg-card", POINT[side])}
				style={side === "top" || side === "bottom" ? { left: point } : { top: point }}
			/>
		</section>
	);
}
