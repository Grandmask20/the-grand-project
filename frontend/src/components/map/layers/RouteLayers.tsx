import { useMemo } from "react";
import { Source } from "react-map-gl/maplibre";
import { useShownSettings } from "@/hooks/app/UseShownSettings";
import { useRouteGraph } from "@/hooks/map/UseGraph";
import { useMapView } from "@/hooks/map/UseMapView";
import { layerOn } from "@/logic/map/AtlasLayers";
import { collection, EMPTY, line, point } from "@/logic/map/Features";
import { routeLayers } from "@/logic/map/OverlayLayers";
import { routeMarks } from "@/logic/Routes";
import { useAppStore } from "@/store/AppStore";
import { MapLayer, MapLayers } from "./MapLayer";

/** The route found (Route tab) or being picked (Route, top bar): the line along its paths and its maps ringed; while
 * tracked, the map you are on marked. */
export function RouteLayers() {
	const { geo } = useMapView();
	const tracked = useAppStore((s) => s.route);
	const draft = useAppStore((s) => s.routeDraft);
	// the route being picked shows over the one tracked until it is tracked, saved or cancelled
	const route = useMemo(() => (draft ? { path: draft, at: undefined } : tracked), [draft, tracked]);
	const graph = useRouteGraph(!!route);
	const settings = useShownSettings(); // (with the layers you're working on: user)
	const on = !settings || layerOn(settings, "Route");

	const { path, nodes, here } = useMemo(() => {
		if (!route || !graph || route.path.length < 1) return { path: EMPTY, nodes: EMPTY, here: EMPTY };
		const coords = graph.line(route.path).map(([x, y]) => geo.toLngLat(x, y));
		const marks = routeMarks(route.path, route.at);
		const points = (ids: number[]) =>
			collection(
				ids.flatMap((id) => {
					const p = graph.at(id);
					return p ? [point(geo.toLngLat(p[0], p[1]), { id })] : [];
				}),
			);
		return {
			path: coords.length > 1 ? collection([line(coords)]) : EMPTY,
			nodes: points(marks.rings),
			here: points(marks.here !== null ? [marks.here] : []),
		};
	}, [geo, route, graph]);
	const specs = useMemo(() => routeLayers(geo, on), [geo, on]);

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
		</>
	);
}
