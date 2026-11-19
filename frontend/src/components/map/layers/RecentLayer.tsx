import { useMemo } from "react";
import { Source } from "react-map-gl/maplibre";
import { useSettings } from "@/hooks/app/UseSettings";
import { useMapView } from "@/hooks/map/UseMapView";
import { useRecent } from "@/hooks/map/UseRecent";
import { layerOn } from "@/logic/map/AtlasLayers";
import { collection, line } from "@/logic/map/Features";
import { recentLayer } from "@/logic/map/OverlayLayers";
import { MapLayer } from "./MapLayer";

/** The screenshots added last, outlined, fading with their age. */
export function RecentLayer() {
	const { geo, meta } = useMapView();
	const settings = useSettings();
	const on = !settings || layerOn(settings, "Recent additions");
	const recent = useRecent(on).data;

	const data = useMemo(() => {
		const fade = Math.max(1, recent?.length ?? 1);
		return collection(
			(recent ?? []).map((r) =>
				line(geo.ring(r.corners), {
					age: r.age,
					picked: r.picked,
					opacity: r.picked ? 1 : 1 - r.age / (fade + 1),
				}),
			),
		);
	}, [geo, recent]);
	const spec = useMemo(() => recentLayer(meta, on), [meta, on]);

	return (
		<Source id="recent" type="geojson" data={data}>
			<MapLayer spec={spec} />
		</Source>
	);
}
