import { Marker } from "react-map-gl/maplibre";
import { usePlayer } from "@/hooks/app/UseSettings";
import { useMapView } from "@/hooks/map/UseMapView";

/** "You are here": the map the player set for routes. */
export function PlayerMarker() {
	const { geo } = useMapView();
	const { player } = usePlayer();
	if (!player) return null;
	const [longitude, latitude] = geo.toLngLat(player.x, player.y);
	return (
		<Marker longitude={longitude} latitude={latitude}>
			<div className="player-marker" title="You are here" />
		</Marker>
	);
}
