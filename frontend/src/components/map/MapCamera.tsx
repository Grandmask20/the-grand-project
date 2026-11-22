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
	const fitTo = useAppStore((s) => s.fitTo);
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
		// with a box over the map's top (the Re-check's changes), the spot goes in the middle of what is left below it
		const top = map.getContainer().getBoundingClientRect().top;
		const below = fly.clearTop ? Math.max(0, fly.clearTop - top) / 2 : 0;
		map.flyTo({
			center: geo.toLngLat(fly.x, fly.y),
			zoom: Math.min(zoom, info.maxzoom),
			speed: 1.6,
			...(below ? { offset: [0, below] as [number, number] } : {}),
		});
	}, [map, geo, info, fly]);

	// an area (a saved route): its corners in the view; the room round it is in the box already (routeBox). Carried
	// out once, then cleared: one asked for while the map loaded is still to do when it's here (it was taken as done:
	// CodeRabbit); another atlas clears it (resetAtlas)
	const fittedArea = useRef(0);
	useEffect(() => {
		if (!fitTo) {
			fittedArea.current = 0;
			return;
		}
		if (fitTo.n === fittedArea.current) return;
		fittedArea.current = fitTo.n;
		useAppStore.setState({ fitTo: null });
		const [x0, y0, x1, y1] = fitTo.box;
		const corners = [geo.toLngLat(x0, y0), geo.toLngLat(x1, y1)];
		const lngs = corners.map((c) => c[0]);
		const lats = corners.map((c) => c[1]);
		map.fitBounds(
			[
				[Math.min(...lngs), Math.min(...lats)],
				[Math.max(...lngs), Math.max(...lats)],
			],
			{ padding: 20, maxZoom: info.maxzoom },
		);
	}, [map, geo, info, fitTo]);

	useEffect(() => {
		if (fit === fitted.current) return;
		fitted.current = fit;
		map.fitBounds(info.bounds, { padding: 30 });
	}, [map, info, fit]);

	return null;
}
