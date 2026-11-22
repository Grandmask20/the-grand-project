import { useMemo } from "react";
import { Source } from "react-map-gl/maplibre";
import { useShownSettings } from "@/hooks/app/UseShownSettings";
import { useRouteGraph } from "@/hooks/map/UseGraph";
import { useMapView } from "@/hooks/map/UseMapView";
import { useRouteRun } from "@/hooks/map/UseRouteRun";
import type { LngLat } from "@/logic/Geo";
import { layerOn } from "@/logic/map/AtlasLayers";
import { collection, EMPTY, line, point } from "@/logic/map/Features";
import { routeLayers } from "@/logic/map/OverlayLayers";
import { runLeg } from "@/logic/RouteRun";
import { routeMarks } from "@/logic/Routes";
import { useAppStore } from "@/store/AppStore";
import { MapLayer, MapLayers } from "./MapLayer";

/** The route found (Route tab) or being picked (Route, top bar): the line along its paths, its dashes marching
 * toward where it goes, and its maps ringed; while tracked, the map you are on marked and a runner walking from it to
 * the next map (untracked: walking the whole route). */
export function RouteLayers() {
	const { geo } = useMapView();
	const tracked = useAppStore((s) => s.route);
	const draft = useAppStore((s) => s.routeDraft);
	// the route being picked shows over the one tracked until it is tracked, saved or cancelled
	const route = useMemo(() => (draft ? { path: draft, at: undefined } : tracked), [draft, tracked]);
	const graph = useRouteGraph(!!route);
	const settings = useShownSettings(); // (with the layers you're working on: user)
	const on = !settings || layerOn(settings, "Route");

	const { path, nodes, here, leg, legMaps } = useMemo(() => {
		if (!route || !graph || route.path.length < 1)
			return { path: EMPTY, nodes: EMPTY, here: EMPTY, leg: [] as LngLat[], legMaps: 0 };
		const coords = graph.line(route.path).map(([x, y]) => geo.toLngLat(x, y));
		const marks = routeMarks(route.path, route.at);
		const points = (ids: number[]) =>
			collection(
				ids.flatMap((id) => {
					const p = graph.at(id);
					return p ? [point(geo.toLngLat(p[0], p[1]), { id })] : [];
				}),
			);
		const walk = runLeg(route.path, route.at);
		return {
			path: coords.length > 1 ? collection([line(coords)]) : EMPTY,
			nodes: points(marks.rings),
			here: points(marks.here !== null ? [marks.here] : []),
			leg: walk.length ? graph.line(walk).map(([x, y]) => geo.toLngLat(x, y)) : [],
			legMaps: walk.length,
		};
	}, [geo, route, graph]);
	const specs = useMemo(() => routeLayers(geo, on), [geo, on]);
	useRouteRun(leg, legMaps, on);

	return (
		<>
			<Source id="route" type="geojson" data={path}>
				<MapLayers specs={specs.line} />
			</Source>
			<Source id="route-nodes" type="geojson" data={nodes}>
				<MapLayer spec={specs.nodes} />
			</Source>
			<Source id="route-here" type="geojson" data={here}>
				<MapLayer spec={specs.here} />
			</Source>
			<Source id="route-runner" type="geojson" data={EMPTY}>
				<MapLayer spec={specs.runner} />
			</Source>
		</>
	);
}
