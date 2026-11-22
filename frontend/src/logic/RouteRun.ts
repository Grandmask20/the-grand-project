import type { LngLat } from "@/logic/Geo";

/**
 * The route runner (MapLibre's "Animate a point along a route" and "ant path" dashes): what moves on the route so it
 * says where it goes (review: the route had very little feedback).
 */

/** The marching dashes, one step after the other: the dash slides along the line (MapLibre's ant path). */
export const DASHES: number[][] = [
	[0, 4, 3],
	[0.5, 4, 2.5],
	[1, 4, 2],
	[1.5, 4, 1.5],
	[2, 4, 1],
	[2.5, 4, 0.5],
	[3, 4, 0],
	[0, 0.5, 3, 3.5],
	[0, 1, 3, 3],
	[0, 1.5, 3, 2.5],
	[0, 2, 3, 2],
	[0, 2.5, 3, 1.5],
	[0, 3, 3, 1],
	[0, 3.5, 3, 0.5],
];

/** A dash step every this many ms. */
export const DASH_MS = 60;
/** The runner's walk, ms per map on its way (at least one walk's worth). */
export const RUN_MS_PER_MAP = 900;

/** The dashes at a time (ms): the step it is at. */
export const dashAt = (ms: number): number[] => DASHES[Math.floor(ms / DASH_MS) % DASHES.length];

/** The maps the runner walks: on a route tracked, from the map you are on to the next one; else the whole route.
 * Fewer than two: none. */
export function runLeg(path: number[], at: number | undefined): number[] {
	const leg = at === undefined ? path : path.slice(at, at + 2);
	return leg.length > 1 ? leg : [];
}

/** A point a share (0..1) of the way along a line, by its length. */
export function alongLine(coords: LngLat[], share: number): LngLat {
	if (coords.length === 0) throw new Error("alongLine: no line");
	if (coords.length === 1) return coords[0];
	const lengths = coords.slice(1).map((c, i) => Math.hypot(c[0] - coords[i][0], c[1] - coords[i][1]));
	const total = lengths.reduce((a, b) => a + b, 0);
	if (total === 0) return coords[0];
	let left = Math.min(Math.max(share, 0), 1) * total;
	for (let i = 0; i < lengths.length; i++) {
		if (left <= lengths[i] || i === lengths.length - 1) {
			const f = lengths[i] ? Math.min(left / lengths[i], 1) : 0;
			const [a, b] = [coords[i], coords[i + 1]];
			return [a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f];
		}
		left -= lengths[i];
	}
	return coords[coords.length - 1];
}
