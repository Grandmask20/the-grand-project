import { useEffect } from "react";
import { useMapLibre } from "@/hooks/map/UseMapLibre";
import { frameLog } from "@/logic/FrameLog";
import { useAppStore } from "@/store/AppStore";

/** While the frame log is on, notes every frame the map draws (the log drawer). */
export function FrameRecorder() {
	const map = useMapLibre();
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
