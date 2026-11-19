import type { ImageSource } from "maplibre-gl";
import { useEffect } from "react";
import { mapAlive, useMapLibre } from "@/hooks/map/UseMapLibre";
import type { LngLat } from "@/logic/Geo";
import { type LayerId, slotOf } from "@/logic/map/LayerOrder";

export type Corners = [LngLat, LngLat, LngLat, LngLat];

interface Props {
	/** The layer and its source (in LAYER_ORDER). */
	id: LayerId;
	url: string;
	corners: Corners;
	opacity: number;
}

/**
 * A picture over 4 corners of the map (the screenshot placed by hand, a question's). Moved, it is not loaded again:
 * react-map-gl's image <Source> loads the picture anew on any change, and a screenshot dragged into place blinked
 * (CodeRabbit). Shown while mounted.
 */
export function PictureLayer({ id, url, corners, opacity }: Props) {
	const map = useMapLibre();

	// the source and layer: made with the picture, kept while it is the same picture
	// biome-ignore lint/correctness/useExhaustiveDependencies: the corners are set below (moved, not made again)
	useEffect(() => {
		map.addSource(id, { type: "image", url, coordinates: corners });
		map.addLayer(
			{ id, type: "raster", source: id, paint: { "raster-fade-duration": 0, "raster-opacity": opacity } },
			slotOf(id),
		);
		return () => {
			if (!mapAlive(map)) return;
			if (map.getLayer(id)) map.removeLayer(id);
			if (map.getSource(id)) map.removeSource(id);
		};
	}, [map, id, url]);

	useEffect(() => {
		(map.getSource(id) as ImageSource | undefined)?.setCoordinates(corners);
	}, [map, id, corners]);

	useEffect(() => {
		if (map.getLayer(id)) map.setPaintProperty(id, "raster-opacity", opacity);
	}, [map, id, opacity]);

	return null;
}
