import type { Map as MapLibreMap } from "maplibre-gl";
import { useEffect } from "react";
import { useAppClient } from "@/hooks/app/UseAppClient";
import { useAppState } from "@/hooks/app/UseAppState";
import type { Geo } from "@/logic/Geo";
import { setData, setImage } from "@/logic/MapStyle";
import { useAppStore } from "@/store/AppStore";

/** Pictures over the map: the screenshot being placed by hand and the one a question is about ("times seen" is
 * drawn by MapTint). */
export function MapImages({ map, geo }: { map: MapLibreMap; geo: Geo }) {
	const app = useAppClient();
	const mode = useAppStore((s) => s.mode);
	const question = useAppState().data?.questions[0] ?? null;

	const ghost = mode.kind === "ghost" ? mode : null;
	useEffect(() => {
		if (!ghost) {
			setImage(map, "ghost-picture", null, null, "selected");
			setData(map, "ghost-line", { type: "FeatureCollection", features: [] });
			return;
		}
		const [x0, y0, x1, y1] = ghost.ghost.box;
		const [cx, cy] = ghost.centre;
		const box: [number, number, number, number] = [x0 + cx, y0 + cy, x1 + cx, y1 + cy];
		setImage(map, "ghost-picture", app.pictureUrl(ghost.ghost.picture), geo.corners(box), "selected", 0.6);
		setData(map, "ghost-line", {
			type: "Feature",
			geometry: {
				type: "LineString",
				coordinates: geo.ring([
					[box[0], box[1]],
					[box[2], box[1]],
					[box[2], box[3]],
					[box[0], box[3]],
				]),
			},
			properties: {},
		});
	}, [map, geo, app, ghost]);

	const preview = question?.preview ?? null;
	useEffect(() => {
		if (!preview) {
			setImage(map, "preview", null, null, "selected");
			return;
		}
		setImage(map, "preview", app.pictureUrl(preview.picture), geo.corners(preview.box), "selected", 0.65);
		const [x0, y0, x1, y1] = preview.box;
		map.fitBounds(geo.boundsOf(x0, y0, x1, y1), { padding: 120, maxZoom: map.getMaxZoom() - 1 });
	}, [map, geo, app, preview]);

	return null;
}
