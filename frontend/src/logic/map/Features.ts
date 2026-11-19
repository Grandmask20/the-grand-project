import type { Geo, LngLat, Point } from "@/logic/Geo";

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

/** A polygon drawn by hand (the lasso): closed, and still a valid ring with too few points to enclose anything. */
export function polygon(geo: Geo, points: Point[]): GeoJSON.Feature {
	const ring = geo.ring(points);
	return {
		type: "Feature",
		geometry: { type: "Polygon", coordinates: [ring.length > 3 ? ring : [...ring, ...ring]] },
		properties: {},
	};
}
