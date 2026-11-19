import { useMemo } from "react";
import { Source } from "react-map-gl/maplibre";
import { useAppState } from "@/hooks/app/UseAppState";
import { useSettings } from "@/hooks/app/UseSettings";
import { useDebugMarks } from "@/hooks/debug/UseDebugMarks";
import { useMapView } from "@/hooks/map/UseMapView";
import { layerOn } from "@/logic/map/AtlasLayers";
import { collection, line, point } from "@/logic/map/Features";
import { markLayers } from "@/logic/map/OverlayLayers";
import { MapLayers } from "./MapLayer";

/** The debug marks (debug mode): a ring on each, and a line between the two maps of a missing or wrong path. */
export function DebugMarkLayers() {
	const { geo } = useMapView();
	const debug = !!useAppState().data?.debug;
	const marks = useDebugMarks(debug).data;
	const settings = useSettings();
	const on = !settings || layerOn(settings, "Debug marks");

	const data = useMemo(() => {
		const features: GeoJSON.Feature[] = [];
		for (const m of marks?.marks ?? []) {
			const ends = m.path?.ends ?? (m.maps.length === 2 ? m.maps.map((q) => [q.x, q.y] as [number, number]) : null);
			const props = { kind: m.kind, label: `D${m.id}` };
			if (ends && (m.kind === "missing path" || m.kind === "wrong path"))
				features.push(
					line(
						ends.map(([x, y]) => geo.toLngLat(x, y)),
						props,
					),
				);
			features.push(point(geo.toLngLat(m.x, m.y), props));
		}
		return collection(features);
	}, [geo, marks]);
	const specs = useMemo(() => markLayers(on), [on]);

	return (
		<Source id="marks" type="geojson" data={data}>
			<MapLayers specs={specs} />
		</Source>
	);
}
