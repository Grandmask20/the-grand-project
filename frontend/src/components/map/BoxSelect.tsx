import { XIcon } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Source } from "react-map-gl/maplibre";
import { BookmarkAll } from "@/components/find/ResultRows";
import type { ResultRow } from "@/domain/find/SearchResult";
import { useRouteGraph } from "@/hooks/map/UseGraph";
import { useMapLibre } from "@/hooks/map/UseMapLibre";
import { useMapView } from "@/hooks/map/UseMapView";
import { collection, EMPTY, point } from "@/logic/map/Features";
import { boxPickedLayer } from "@/logic/map/OverlayLayers";
import { useAppStore } from "@/store/AppStore";
import { MapLayer } from "./layers/MapLayer";

/** Less than this many screen px across is a click, not a box. */
const LEAST = 6;

type Box = { x0: number; y0: number; x1: number; y1: number };

/** The maps whose spot on the screen is in a box (screen px, the map's own corner at 0, 0). */
export function mapsInBox(at: [number, number][], ids: number[], b: Box): number[] {
	const [l, r] = [Math.min(b.x0, b.x1), Math.max(b.x0, b.x1)];
	const [t, d] = [Math.min(b.y0, b.y1), Math.max(b.y0, b.y1)];
	return ids.filter((_, i) => at[i][0] >= l && at[i][0] <= r && at[i][1] >= t && at[i][1] <= d);
}

/**
 * Box select (MapLibre's "Select features with boxZoomEnd"): Shift-drag a box on the map to pick every map in it.
 * They are ringed, and a bar over the map's bottom says how many with Bookmark all (into a group) and its x (or Esc)
 * to let them go. Shift-drag again for another box; Shift held, the map doesn't pan (MapPan) and MapLibre's own
 * Shift-drag zoom is off (AtlasMap).
 */
export function BoxSelect() {
	const map = useMapLibre();
	const { geo } = useMapView();
	const graph = useRouteGraph(true);
	const picked = useAppStore((s) => s.boxPicked);
	const setPicked = useAppStore((s) => s.setBoxPicked);
	const [box, setBox] = useState<Box | null>(null);

	useEffect(() => {
		const el = map.getCanvasContainer();
		let drag: Box | null = null;
		const local = (e: MouseEvent): [number, number] => {
			const r = el.getBoundingClientRect();
			return [e.clientX - r.left, e.clientY - r.top];
		};
		const down = (e: MouseEvent) => {
			if (e.button !== 0 || !e.shiftKey || useAppStore.getState().mode.kind !== "normal") return;
			e.preventDefault();
			const [x, y] = local(e);
			drag = { x0: x, y0: y, x1: x, y1: y };
			setBox(drag);
		};
		const move = (e: MouseEvent) => {
			if (!drag) return;
			const [x, y] = local(e);
			drag = { ...drag, x1: x, y1: y };
			setBox(drag);
		};
		const up = () => {
			const b = drag;
			drag = null;
			setBox(null);
			if (!b || !graph || Math.max(Math.abs(b.x1 - b.x0), Math.abs(b.y1 - b.y0)) < LEAST) return;
			const all = graph.positions();
			const at = all.map(([, [x, y]]) => {
				const p = map.project(geo.toLngLat(x, y));
				return [p.x, p.y] as [number, number];
			});
			setPicked(
				mapsInBox(
					at,
					all.map(([id]) => id),
					b,
				),
			);
		};
		const esc = (e: KeyboardEvent) => {
			if (e.key === "Escape" && useAppStore.getState().boxPicked.length) setPicked([]);
		};
		el.addEventListener("mousedown", down);
		window.addEventListener("mousemove", move);
		window.addEventListener("mouseup", up);
		window.addEventListener("keydown", esc);
		return () => {
			el.removeEventListener("mousedown", down);
			window.removeEventListener("mousemove", move);
			window.removeEventListener("mouseup", up);
			window.removeEventListener("keydown", esc);
		};
	}, [map, geo, graph, setPicked]);

	const { rings, rows } = useMemo(() => {
		if (!graph || !picked.length) return { rings: EMPTY, rows: [] as ResultRow[] };
		const at = picked.flatMap((id) => {
			const p = graph.at(id);
			return p ? [[id, p] as const] : [];
		});
		return {
			rings: collection(at.map(([id, [x, y]]) => point(geo.toLngLat(x, y), { id }))),
			rows: at.map(([id, [x, y]]): ResultRow => ({ kind: "node", id, label: `Map #${id}`, x, y })),
		};
	}, [graph, picked, geo]);
	const spec = useMemo(() => boxPickedLayer(geo), [geo]);

	return (
		<>
			<Source id="box-picked" type="geojson" data={rings}>
				<MapLayer spec={spec} />
			</Source>
			{box && (
				<div
					data-testid="box-select"
					className="pointer-events-none absolute z-20 border-2 border-dashed border-[#4da3ff] bg-[#4da3ff]/10"
					style={{
						left: Math.min(box.x0, box.x1),
						top: Math.min(box.y0, box.y1),
						width: Math.abs(box.x1 - box.x0),
						height: Math.abs(box.y1 - box.y0),
					}}
				/>
			)}
			{picked.length > 0 && (
				<div
					role="toolbar"
					aria-label="Maps picked"
					className="absolute bottom-10 left-1/2 z-30 flex -translate-x-1/2 items-center gap-3 rounded-md border bg-card/95 px-3 py-1.5 text-sm shadow"
				>
					<span>
						{picked.length} map{picked.length === 1 ? "" : "s"} picked
					</span>
					<BookmarkAll rows={rows} name="Picked" />
					<button
						type="button"
						aria-label="Let the picked maps go"
						title="Let them go (Esc)"
						onClick={() => setPicked([])}
						className="rounded p-0.5 text-muted-foreground hover:bg-accent hover:text-foreground"
					>
						<XIcon className="size-4" />
					</button>
				</div>
			)}
		</>
	);
}
