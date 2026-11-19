import type { Map as MapLibreMap } from "maplibre-gl";
import { useEffect } from "react";
import { frameLog } from "@/logic/FrameLog";
import { useAppStore } from "@/store/AppStore";

/** While the frame log is on, notes every frame the map draws (Log tab). */
export function FrameRecorder({ map }: { map: MapLibreMap }) {
	const on = useAppStore((s) => s.frameLog);
	useEffect(() => {
		if (!on) return;
		const onRender = () => frameLog.frame(map.getZoom(), map.isMoving() ? "moving" : "");
		map.on("render", onRender);
		return () => {
			map.off("render", onRender);
		};
	}, [map, on]);
	return null;
}
