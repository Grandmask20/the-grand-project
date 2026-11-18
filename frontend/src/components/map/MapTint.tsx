import type { Map as MapLibreMap } from "maplibre-gl";
import { useEffect } from "react";
import { useSettings } from "@/hooks/app/UseSettings";
import { useFrames } from "@/hooks/replay/UseFrames";
import { rampColour } from "@/logic/Colours";
import type { Geo } from "@/logic/Geo";
import { EMPTY, setData } from "@/logic/MapStyle";
import { revealed } from "@/logic/Replay";
import { useAppStore } from "@/store/AppStore";

/** "Colour by" session or oldest to newest: each screenshot's area tinted (newer over older; while replaying, only
 * those revealed). */
export function MapTint({ map, geo }: { map: MapLibreMap; geo: Geo }) {
	const mode = useSettings()?.style.age_tint ?? "off";
	const on = mode === "by session" || mode === "oldest to newest";
	const plan = useAppStore((s) => s.replay?.plan ?? null);
	const frames = useFrames(on || plan !== null);
	const step = useAppStore((s) => (s.replay ? Math.ceil(s.replay.pos) : null));

	useEffect(() => {
		const f = frames.data;
		if (!on || !f) {
			setData(map, "frames", EMPTY);
			return;
		}
		const pos = step ?? Number.POSITIVE_INFINITY;
		const features: GeoJSON.Feature[] = [];
		for (const i of f.order) {
			const fr = f.frames[i];
			if (!fr.corners.length || !revealed(plan, i, pos)) continue;
			const colour =
				mode === "by session" ? f.sessions[fr.session % f.sessions.length] : rampColour(f.ramp, fr.rank);
			features.push({
				type: "Feature",
				geometry: { type: "Polygon", coordinates: [geo.ring(fr.corners)] },
				properties: { colour },
			});
		}
		setData(map, "frames", { type: "FeatureCollection", features });
	}, [map, geo, on, mode, frames.data, plan, step]);

	return null;
}
