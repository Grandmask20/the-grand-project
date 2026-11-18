import { type Map as MapLibreMap, Marker } from "maplibre-gl";
import { useEffect, useRef } from "react";
import { useSettings } from "@/hooks/app/UseSettings";
import type { Geo } from "@/logic/Geo";

/** "You are here": the map the player set for routes. */
export function PlayerMarker({ map, geo }: { map: MapLibreMap; geo: Geo }) {
	const player = useSettings()?.ui.player ?? null;
	const marker = useRef<Marker | null>(null);

	useEffect(() => {
		if (!player) {
			marker.current?.remove();
			return;
		}
		if (!marker.current) {
			const el = document.createElement("div");
			el.className = "player-marker";
			el.title = "You are here";
			marker.current = new Marker({ element: el });
		}
		marker.current.setLngLat(geo.toLngLat(player.x, player.y)).addTo(map);
	}, [map, geo, player]);

	useEffect(
		() => () => {
			marker.current?.remove();
		},
		[],
	);
	return null;
}
