import { useEffect, useRef } from "react";
import { useMapLibre } from "@/hooks/map/UseMapLibre";
import { useMapView } from "@/hooks/map/UseMapView";
import { useAppStore } from "@/store/AppStore";

/** Moves the map when asked (Find, lists, Fit) and remembers where it is (kept when the map is made again). */
export function MapCamera() {
	const map = useMapLibre();
	const { geo, info } = useMapView();
	const fly = useAppStore((s) => s.fly);
	const fit = useAppStore((s) => s.fitAtlas);
	const setCamera = useAppStore((s) => s.setCamera);

	useEffect(() => {
		const save = () => {
			const c = map.getCenter();
			const [x, y] = geo.toAtlas(c.lng, c.lat);
			setCamera({ x, y, px: geo.pxPerUnit(map.getZoom()), bearing: map.getBearing(), pitch: map.getPitch() });
		};
		map.on("moveend", save);
		return () => {
			map.off("moveend", save);
		};
	}, [map, geo, setCamera]);

	// each fly / fit request is carried out once: the map's info changes with every tile version (hiding a bookmark
	// group, the replay), which flew back to the last Find result (user; CodeRabbit). Requests made before this map
	// was made (an earlier atlas or map image) are skipped too.
	const flown = useRef(fly?.n ?? 0);
	const fitted = useRef(fit);
	useEffect(() => {
		if (!fly) {
			flown.current = 0; // (cleared with the store: the next request starts at 1 again, CodeRabbit)
			return;
		}
		if (fly.n === flown.current) return;
		flown.current = fly.n;
		const zoom = Math.max(map.getZoom(), geo.zoomFor(fly.px ?? 1));
		map.flyTo({ center: geo.toLngLat(fly.x, fly.y), zoom: Math.min(zoom, info.maxzoom), speed: 1.6 });
	}, [map, geo, info, fly]);

	useEffect(() => {
		if (fit === fitted.current) return;
		fitted.current = fit;
		map.fitBounds(info.bounds, { padding: 30 });
	}, [map, info, fit]);

	return null;
}
