import type { Map as MapLibreMap } from "maplibre-gl";
import { useEffect } from "react";
import { useAppState } from "@/hooks/app/UseAppState";
import { useSettings } from "@/hooks/app/UseSettings";
import { useDebugMarks } from "@/hooks/debug/UseDebugMarks";
import { useRouteGraph } from "@/hooks/map/UseGraph";
import { useRecent } from "@/hooks/map/UseRecent";
import type { Geo } from "@/logic/Geo";
import { EMPTY, setData } from "@/logic/MapStyle";
import { useAppStore } from "@/store/AppStore";

const point = (c: [number, number], props: Record<string, unknown> = {}): GeoJSON.Feature => ({
	type: "Feature",
	geometry: { type: "Point", coordinates: c },
	properties: props,
});

const collection = (features: GeoJSON.Feature[]): GeoJSON.FeatureCollection => ({
	type: "FeatureCollection",
	features,
});

/** What the page draws over the tiles: the selection, Find's results, the go-to mark, the route, the recent
 * additions' outlines and the debug marks. */
export function MapOverlays({ map, geo }: { map: MapLibreMap; geo: Geo }) {
	const selected = useAppStore((s) => s.selected);
	const results = useAppStore((s) => s.results);
	const goto = useAppStore((s) => s.goto);
	const route = useAppStore((s) => s.route);
	const state = useAppState().data;
	const settings = useSettings();
	const graph = useRouteGraph(!!route);
	const recent = useRecent(settings?.layers["Recent additions"] !== false);
	const marks = useDebugMarks(!!state?.debug);

	useEffect(() => {
		setData(map, "selected", selected ? collection([point(geo.toLngLat(selected.x, selected.y))]) : EMPTY);
		// a selected path: the whole path lit up, not a ring where it was clicked (as the old window)
		setData(
			map,
			"selected-path",
			selected?.kind === "path" && selected.line?.length
				? collection([
						{
							type: "Feature",
							geometry: { type: "LineString", coordinates: selected.line.map(([x, y]) => geo.toLngLat(x, y)) },
							properties: {},
						},
					])
				: EMPTY,
		);
	}, [map, geo, selected]);

	// the flat ring: not for a path (lit up instead), nor for an icon while tilted (the 3D icon wears its own ring;
	// it came back wrong after switching views: user)
	const tilted = useAppStore((s) => (s.camera?.pitch ?? 0) > 1);
	const icons3d = tilted && settings?.layers.Icons !== false;
	useEffect(() => {
		const hide = selected?.kind === "path" || (selected?.kind === "icon" && icons3d);
		if (map.getLayer("selected")) map.setLayoutProperty("selected", "visibility", hide ? "none" : "visible");
	}, [map, selected, icons3d]);

	useEffect(() => {
		setData(map, "hits", collection(results.slice(0, 2000).map((r) => point(geo.toLngLat(r.x, r.y)))));
	}, [map, geo, results]);

	useEffect(() => {
		setData(map, "goto", goto ? collection([point(geo.toLngLat(goto[0], goto[1]))]) : EMPTY);
	}, [map, geo, goto]);

	useEffect(() => {
		if (!route || !graph || route.path.length < 1) {
			setData(map, "route", EMPTY);
			setData(map, "route-nodes", EMPTY);
			return;
		}
		const line = graph.line(route.path).map(([x, y]) => geo.toLngLat(x, y));
		setData(
			map,
			"route",
			line.length > 1
				? { type: "Feature", geometry: { type: "LineString", coordinates: line }, properties: {} }
				: EMPTY,
		);
		setData(
			map,
			"route-nodes",
			collection(
				route.path.slice(1).flatMap((id) => {
					const p = graph.at(id);
					return p ? [point(geo.toLngLat(p[0], p[1]), { id })] : [];
				}),
			),
		);
	}, [map, geo, route, graph]);

	useEffect(() => {
		const fade = Math.max(1, recent.data?.length ?? 1);
		setData(
			map,
			"recent",
			collection(
				(recent.data ?? []).map((r) => ({
					type: "Feature",
					geometry: { type: "LineString", coordinates: geo.ring(r.corners) },
					properties: { age: r.age, picked: r.picked, opacity: r.picked ? 1 : 1 - r.age / (fade + 1) },
				})),
			),
		);
	}, [map, geo, recent.data]);

	useEffect(() => {
		const features: GeoJSON.Feature[] = [];
		for (const m of marks.data?.marks ?? []) {
			const ends = m.path?.ends ?? (m.maps.length === 2 ? m.maps.map((q) => [q.x, q.y] as [number, number]) : null);
			if (ends && (m.kind === "missing path" || m.kind === "wrong path"))
				features.push({
					type: "Feature",
					geometry: { type: "LineString", coordinates: ends.map(([x, y]) => geo.toLngLat(x, y)) },
					properties: { kind: m.kind, label: `D${m.id}` },
				});
			features.push(point(geo.toLngLat(m.x, m.y), { kind: m.kind, label: `D${m.id}` }));
		}
		setData(map, "marks", collection(features));
	}, [map, geo, marks.data]);

	return null;
}
