import type { Map as MapLibreMap } from "maplibre-gl";
import { useEffect, useState } from "react";
import type { Meta } from "@/domain/app/Meta";
import { useSettings } from "@/hooks/app/UseSettings";
import type { Geo } from "@/logic/Geo";
import { applyLook } from "@/logic/MapStyle";
import { useAppStore } from "@/store/AppStore";

/** Keeps the map's layers in step with the settings, the tilt, Find's highlight and the replay. */
export function MapLook({ map, geo, meta }: { map: MapLibreMap; geo: Geo; meta: Meta }) {
	const settings = useSettings();
	const highlight = useAppStore((s) => s.highlight);
	const lookTick = useAppStore((s) => s.lookTick);
	const [tilted, setTilted] = useState(() => map.getPitch() > 1);
	// the replay's position matters to the layers only for the 3D models (tilted): the fog hides the rest, so flat
	// the look isn't applied again every frame (that redid every layer and the page fell behind: user)
	const replayPos = useAppStore((s) => (s.replay ? (tilted ? s.replay.pos : 0) : null));

	useEffect(() => {
		const onPitch = () => setTilted(map.getPitch() > 1);
		map.on("pitchend", onPitch);
		return () => {
			map.off("pitchend", onPitch);
		};
	}, [map]);

	useEffect(() => {
		if (!settings) return;
		const tint = settings.style.age_tint;
		applyLook(map, geo, meta, {
			settings,
			background: settings.ui.background ?? "picture",
			tilted,
			highlight,
			replayPos,
			tint: tint === "by session" || tint === "oldest to newest" ? "frames" : tint === "times seen" ? "heat" : "off",
		});
	}, [map, geo, meta, settings, tilted, highlight, replayPos, lookTick]);

	return null;
}
