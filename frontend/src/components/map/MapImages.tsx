import type { Map as MapLibreMap } from "maplibre-gl";
import { useEffect } from "react";
import { useAppClient } from "@/hooks/app/UseAppClient";
import { useAppState } from "@/hooks/app/UseAppState";
import { useSettings } from "@/hooks/app/UseSettings";
import { useHeat } from "@/hooks/replay/UseHeat";
import type { Geo } from "@/logic/Geo";
import { setData, setImage } from "@/logic/MapStyle";
import { useAppStore } from "@/store/AppStore";

/** Pictures over the map: the screenshot being placed by hand, the one a question is about, and "times seen". */
export function MapImages({ map, geo }: { map: MapLibreMap; geo: Geo }) {
	const app = useAppClient();
	const mode = useAppStore((s) => s.mode);
	const replay = useAppStore((s) => s.replay);
	const question = useAppState().data?.questions[0] ?? null;
	const settings = useSettings();
	const heatOn = settings?.style.age_tint === "times seen";
	// while replaying, the heat grows with it (fetched in about 40 steps over the whole replay)
	const q = replay ? Math.max(1, Math.ceil(replay.plan.n_steps / 40)) : 1;
	const upto = replay ? Math.ceil(replay.pos / q) * q : undefined;
	const heat = useHeat(heatOn, upto);

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
			geometry: { type: "LineString", coordinates: geo.ring([[box[0], box[1]], [box[2], box[1]], [box[2], box[3]], [box[0], box[3]]]) },
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

	const box = heatOn ? (heat.data?.box ?? null) : null;
	useEffect(() => {
		setImage(map, "heat", box ? app.heatUrl(upto, Date.now()) : null, box ? geo.corners(box) : null, "biomes", 0.55);
	}, [map, geo, app, box, upto]);

	return null;
}
