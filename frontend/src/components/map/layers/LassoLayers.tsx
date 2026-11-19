import { useMemo } from "react";
import { Source } from "react-map-gl/maplibre";
import { useMapView } from "@/hooks/map/UseMapView";
import type { Point } from "@/logic/Geo";
import { EMPTY, polygon } from "@/logic/map/Features";
import { lassoLayers } from "@/logic/map/OverlayLayers";
import { MapLayers } from "./MapLayer";

/** The lasso drawn round the maps of a city biome (null: none). */
export function LassoLayers({ points }: { points: Point[] | null }) {
	const { geo } = useMapView();
	const data = useMemo(() => (points ? polygon(geo, points) : EMPTY), [geo, points]);
	const specs = useMemo(() => lassoLayers(), []);
	return (
		<Source id="lasso" type="geojson" data={data}>
			<MapLayers specs={specs} />
		</Source>
	);
}
