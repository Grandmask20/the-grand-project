import type { MapMouseEvent } from "maplibre-gl";
import { useEffect, useState } from "react";
import { useGeo } from "@/hooks/map/UseGeo";
import { useAppStore } from "@/store/AppStore";

/** Where the mouse is on the atlas, and the zoom ("" off the map): its own hook, so only what shows it redraws on
 * every mouse move (the whole status bar did: CodeRabbit). */
export function useCursorAt(): string {
	const map = useAppStore((s) => s.map);
	const geo = useGeo();
	const [at, setAt] = useState("");
	useEffect(() => {
		if (!map || !geo) return;
		const move = (e: MapMouseEvent) => {
			const [x, y] = geo.toAtlas(e.lngLat.lng, e.lngLat.lat);
			setAt(`x ${x.toFixed(0)}  y ${y.toFixed(0)}   zoom ${geo.pxPerUnit(map.getZoom()).toFixed(2)}`);
		};
		map.on("mousemove", move);
		return () => {
			map.off("mousemove", move);
		};
	}, [map, geo]);
	return at;
}
