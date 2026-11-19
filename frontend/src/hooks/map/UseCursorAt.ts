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
		// empty off the map: when the mouse leaves it, and with no map (it kept the last place: CodeRabbit)
		setAt("");
		if (!map || !geo) return;
		const move = (e: MapMouseEvent) => {
			const [x, y] = geo.toAtlas(e.lngLat.lng, e.lngLat.lat);
			setAt(`x ${x.toFixed(0)}  y ${y.toFixed(0)}   zoom ${geo.pxPerUnit(map.getZoom()).toFixed(2)}`);
		};
		const out = () => setAt("");
		map.on("mousemove", move);
		map.on("mouseout", out);
		return () => {
			map.off("mousemove", move);
			map.off("mouseout", out);
		};
	}, [map, geo]);
	return at;
}
