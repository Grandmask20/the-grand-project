import type { Map as MapLibreMap } from "maplibre-gl";
import { useEffect } from "react";
import { useBookmarks } from "@/hooks/bookmarks/UseBookmarks";
import type { Geo } from "@/logic/Geo";
import { setData } from "@/logic/MapStyle";

/** The bookmarks on the map, drawn from the page's bookmark list: the ones neither hidden nor in a hidden group. */
export function MapBookmarks({ map, geo }: { map: MapLibreMap; geo: Geo }) {
	const bookmarks = useBookmarks().data;

	useEffect(() => {
		const features: GeoJSON.Feature[] = [];
		for (const g of bookmarks?.groups ?? [])
			for (const b of g.items)
				if (b.shown)
					features.push({
						type: "Feature",
						id: b.id,
						geometry: { type: "Point", coordinates: geo.toLngLat(b.x, b.y) },
						properties: { id: b.id, name: b.name },
					});
		setData(map, "bookmarks", { type: "FeatureCollection", features });
	}, [map, geo, bookmarks]);

	return null;
}
