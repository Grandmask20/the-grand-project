import type { Map as MapLibreMap } from "maplibre-gl";
import { useEffect } from "react";
import type { Meta } from "@/domain/app/Meta";
import { useFog } from "@/hooks/replay/UseFog";
import { useFrames } from "@/hooks/replay/UseFrames";
import type { Geo } from "@/logic/Geo";
import { EMPTY, setData } from "@/logic/MapStyle";
import { fogBands } from "@/logic/Replay";
import { useAppStore } from "@/store/AppStore";
import { MapTint } from "./MapTint";

/** The replay on the map: the ground not revealed yet under fog, and the screenshots coming in outlined. */
export function ReplayLayers({ map, geo }: { map: MapLibreMap; geo: Geo; meta: Meta }) {
	const replay = useAppStore((s) => s.replay);
	const planKey = replay
		? `${replay.plan.kind}-${replay.plan.n_steps}-${replay.plan.settings.per_step}-${replay.plan.area}`
		: null;
	const fog = useFog(planKey);
	const frames = useFrames(!!replay);

	const open = replay !== null;
	useEffect(() => {
		setData(map, "fog", open && fog.data ? { type: "FeatureCollection", features: fog.data.features } : EMPTY);
	}, [map, open, fog.data]);

	const bands = fog.data?.bands ?? 0;
	const pos = replay?.pos ?? null;
	const nSteps = replay?.plan.n_steps ?? 1;
	useEffect(() => {
		if (pos === null || !bands) {
			map.setFilter("fog-full", ["==", ["get", "band"], -1]);
			map.setFilter("fog-fading", ["==", ["get", "band"], -1]);
			return;
		}
		const b = fogBands(pos, nSteps, bands);
		map.setFilter("fog-full", ["==", ["get", "band"], b.full]);
		map.setFilter("fog-fading", ["==", ["get", "band"], b.fading]);
		map.setPaintProperty("fog-fading", "fill-opacity", 1 - b.fade);
	}, [map, pos, nSteps, bands]);

	// the screenshots of the step coming in, outlined (not when revealing by area)
	const cur = pos === null ? -1 : Math.ceil(pos - 1e-9) - 1;
	const plan = replay?.plan ?? null;
	useEffect(() => {
		if (!plan || !frames.data || plan.area || cur < 0 || (pos ?? 0) >= plan.n_steps) {
			setData(map, "outline", EMPTY);
			return;
		}
		const features: GeoJSON.Feature[] = [];
		plan.step_of.forEach((s, i) => {
			const f = frames.data?.frames[i];
			if (s === cur && f?.corners.length)
				features.push({
					type: "Feature",
					geometry: { type: "LineString", coordinates: geo.ring(f.corners) },
					properties: {},
				});
		});
		setData(map, "outline", { type: "FeatureCollection", features });
	}, [map, geo, plan, frames.data, cur, pos]);

	return <MapTint map={map} geo={geo} />;
}
