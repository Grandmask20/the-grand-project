import { useMemo } from "react";
import { Source } from "react-map-gl/maplibre";
import { useSettings } from "@/hooks/app/UseSettings";
import { useRouteGraph } from "@/hooks/map/UseGraph";
import { useMapView } from "@/hooks/map/UseMapView";
import { layerOn } from "@/logic/map/AtlasLayers";
import { collection, EMPTY, line, point } from "@/logic/map/Features";
import { routeLayers } from "@/logic/map/OverlayLayers";
import { useAppStore } from "@/store/AppStore";
import { MapLayer, MapLayers } from "./MapLayer";

/** The route found (Route tab): the line along its paths and its maps ringed. */
export function RouteLayers() {
	const { geo } = useMapView();
	const route = useAppStore((s) => s.route);
	const graph = useRouteGraph(!!route);
	const settings = useSettings();
	const on = !settings || layerOn(settings, "Route");

	const { path, nodes } = useMemo(() => {
		if (!route || !graph || route.path.length < 1) return { path: EMPTY, nodes: EMPTY };
		const coords = graph.line(route.path).map(([x, y]) => geo.toLngLat(x, y));
		return {
			path: coords.length > 1 ? collection([line(coords)]) : EMPTY,
			nodes: collection(
				route.path.slice(1).flatMap((id) => {
					const p = graph.at(id);
					return p ? [point(geo.toLngLat(p[0], p[1]), { id })] : [];
				}),
			),
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
		</>
	);
}
