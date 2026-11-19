import type { Geo, LngLat } from "@/logic/Geo";

/** GeoJSON for the layers the page fills itself. */
export const EMPTY: GeoJSON.FeatureCollection = { type: "FeatureCollection", features: [] };

export const collection = (features: GeoJSON.Feature[]): GeoJSON.FeatureCollection => ({
	type: "FeatureCollection",
	features,
});

export const point = (c: LngLat, properties: Record<string, unknown> = {}): GeoJSON.Feature => ({
	type: "Feature",
	geometry: { type: "Point", coordinates: c },
	properties,
});

export const line = (coordinates: LngLat[], properties: Record<string, unknown> = {}): GeoJSON.Feature => ({
	type: "Feature",
	geometry: { type: "LineString", coordinates },
	properties,
});

/** A box's outline, [x0, y0, x1, y1] in atlas units. */
export const boxLine = (geo: Geo, [x0, y0, x1, y1]: [number, number, number, number]): GeoJSON.Feature =>
	line(
		geo.ring([
			[x0, y0],
			[x1, y0],
			[x1, y1],
			[x0, y1],
		]),
	);
