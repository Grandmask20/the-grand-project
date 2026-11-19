import type { Map as MapLibreMap } from "maplibre-gl";
import { useMap } from "react-map-gl/maplibre";

/** The MapLibre map under react-map-gl's <Map>, for what its components don't cover (events, custom layers, canvas
 * pictures, the camera). */
export function useMapLibre(): MapLibreMap {
	const map = useMap().current;
	if (!map) throw new Error("useMapLibre outside <Map>");
	return map.getMap();
}

/** Whether the map is still there: react-map-gl removes it before its children's clean-ups run (React runs a
 * removed tree's clean-ups from the top), and a map gone throws on layer calls (the timelapse fog blanked the page
 * when another atlas opened: user). */
export const mapAlive = (map: MapLibreMap): boolean => !(map as unknown as { _removed?: boolean })._removed;
