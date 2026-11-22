import type { MapLayerMouseEvent } from "maplibre-gl";
import { useEffect, useMemo, useState } from "react";
import { Source } from "react-map-gl/maplibre";
import { IconPicture } from "@/components/common/IconPicture";
import { useTypes } from "@/hooks/find/UseTypes";
import { useRouteGraph } from "@/hooks/map/UseGraph";
import { useMapLibre } from "@/hooks/map/UseMapLibre";
import { useMapView } from "@/hooks/map/UseMapView";
import { collection, EMPTY, line, point } from "@/logic/map/Features";
import { hoverLayers } from "@/logic/map/OverlayLayers";
import { useAppStore } from "@/store/AppStore";
import { MapLayer } from "./layers/MapLayer";

/** The layers a map node is drawn in (the style picked shows one of them). */
const MAP_LAYERS = ["maps", "maps-square", "maps-icon"];
/** Screen px between the mouse and the tip. */
const OFF = 14;

/**
 * Hover peek (MapLibre's "Create a hover effect" and "Display a popup on hover"): the map under the mouse, its paths
 * and the maps they go to light up in teal, and a small tip by the mouse names it with its icons, to read the atlas
 * without clicking every map. Only on the flat map, with no map mode on and no button held.
 */
export function HoverPeek() {
	const map = useMapLibre();
	const { geo } = useMapView();
	const graph = useRouteGraph(true);
	const types = useTypes();
	const [hover, setHover] = useState<{ id: number; x: number; y: number } | null>(null);

	useEffect(() => {
		const layers = () => MAP_LAYERS.filter((id) => map.getLayer(id));
		const move = (e: MapLayerMouseEvent) => {
			const calm = useAppStore.getState().mode.kind === "normal" && !(e.originalEvent?.buttons ?? 0);
			const on = calm && map.getPitch() <= 1 ? layers() : [];
			const f = on.length ? map.queryRenderedFeatures(e.point, { layers: on })[0] : undefined;
			const id = f?.properties?.id;
			setHover((h) => {
				if (typeof id !== "number") return h ? null : h;
				return { id, x: e.point.x, y: e.point.y };
			});
		};
		const out = () => setHover(null);
		map.on("mousemove", move);
		map.on("mouseout", out);
		return () => {
			map.off("mousemove", move);
			map.off("mouseout", out);
		};
	}, [map]);

	const id = hover?.id ?? null;
	const lit = useMemo(() => {
		if (id === null || !graph?.has(id)) return EMPTY;
		const at = (n: number) => {
			const p = graph.at(n);
			return p ? geo.toLngLat(p[0], p[1]) : null;
		};
		const next = graph.neighbours(id);
		return collection([
			...next.map((n) => line(graph.line([id, n]).map(([x, y]) => geo.toLngLat(x, y)))),
			...[id, ...next].flatMap((n) => {
				const c = at(n);
				return c ? [point(c, { id: n, here: n === id })] : [];
			}),
		]);
	}, [id, graph, geo]);
	const specs = useMemo(() => hoverLayers(geo), [geo]);
	const labelOf = useMemo(
		() =>
			new Map((types.data?.sections.find((s) => s.title === "Map icons")?.rows ?? []).map((r) => [r.icon, r.label])),
		[types.data],
	);
	const icons = id !== null && graph ? [...new Set(graph.iconsOf(id))] : [];

	return (
		<>
			<Source id="hover-peek" type="geojson" data={lit}>
				<MapLayer spec={specs.lines} />
				<MapLayer spec={specs.maps} />
			</Source>
			{hover && (
				<div
					role="tooltip"
					className="pointer-events-none absolute z-30 flex max-w-64 flex-col gap-1 rounded-md border bg-card/95 px-2 py-1 text-xs shadow"
					style={{ left: hover.x + OFF, top: hover.y + OFF }}
				>
					<span className="font-semibold">
						Map #{hover.id}
						{graph ? ` · ${graph.neighbours(hover.id).length} paths` : ""}
					</span>
					{icons.length > 0 && (
						<span className="flex flex-wrap gap-1">
							{icons.map((ic) => (
								<span key={ic} className="flex items-center gap-1">
									<IconPicture name={ic} size={14} />
									{labelOf.get(ic) ?? ic}
								</span>
							))}
						</span>
					)}
				</div>
			)}
		</>
	);
}
