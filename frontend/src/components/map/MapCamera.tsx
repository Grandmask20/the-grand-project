import type { Map as MapLibreMap } from "maplibre-gl";
import { useEffect } from "react";
import type { MapInfo } from "@/domain/map/MapInfo";
import type { Geo } from "@/logic/Geo";
import { useAppStore } from "@/store/AppStore";

/** Moves the map when asked (Find, lists, Fit) and remembers where it is (kept when the map is made again). */
export function MapCamera({ map, geo, info }: { map: MapLibreMap; geo: Geo; info: MapInfo }) {
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

	useEffect(() => {
		if (!fly) return;
		const zoom = Math.max(map.getZoom(), geo.zoomFor(fly.px ?? 1));
		map.flyTo({ center: geo.toLngLat(fly.x, fly.y), zoom: Math.min(zoom, info.maxzoom), speed: 1.6 });
	}, [map, geo, info, fly]);

	useEffect(() => {
		if (fit) map.fitBounds(info.bounds, { padding: 30 });
	}, [map, info, fit]);

	return null;
}
