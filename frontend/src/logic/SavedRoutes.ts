import type { SavedRoute } from "@/domain/bookmarks/Bookmarks";
import type { Point } from "./Geo";
import type { RouteGraph } from "./Routes";

/** A route as maps: its legs of map numbers, the main one first. Each branch starts on a map of the route (user: a
 * map added off the route's side is a second path from where it splits off). */
export type Legs = number[][];

/** A saved route's lines, its main leg's first (one from before branches: its one line). */
export function routeLines(r: SavedRoute): Point[][] {
	return r.legs ? r.legs.map((l) => l.line) : r.line ? [r.line] : [];
}

/** A saved route's legs on the atlas as it is now: its maps' spots to the maps there (one saved before routes kept
 * their maps: the route between its line's ends). Null when they aren't on this atlas any more. */
export function legsOf(r: SavedRoute, graph: RouteGraph): Legs | null {
	if (r.legs) {
		const legs: Legs = [];
		for (const leg of r.legs) {
			const ids: number[] = [];
			for (const [x, y] of leg.maps) {
				const id = graph.nearest(x, y);
				if (id === null) return null;
				if (ids[ids.length - 1] !== id) ids.push(id);
			}
			legs.push(ids);
		}
		return legs[0]?.length >= 2 ? legs.filter((l, i) => i === 0 || l.length >= 2) : null;
	}
	const line = r.line ?? [];
	if (line.length < 2) return null;
	const [a, b] = [line[0], line[line.length - 1]].map(([x, y]) => graph.nearest(x, y));
	if (a === null || b === null || a === b) return null;
	const path = graph.shortest(a, (u) => u === b);
	return path ? [path] : null;
}

/** The route's map nearest a spot, within `reach` (atlas units), or null. */
export function nearestOn(legs: Legs, graph: RouteGraph, at: Point, reach: number): number | null {
	let best: number | null = null;
	let bd = reach;
	for (const id of new Set(legs.flat())) {
		const p = graph.at(id);
		const d = p ? Math.hypot(p[0] - at[0], p[1] - at[1]) : Number.POSITIVE_INFINITY;
		if (d <= bd) {
			bd = d;
			best = id;
		}
	}
	return best;
}

/** The way a route is run: the main leg, and at each map the branches off it first, there and back (user's example:
 * 1, 2, 3, the branch's 4, then on to 5 and 6). The maps passed again on the way back are in it too. */
export function visitOrder(legs: Legs): number[] {
	const out: number[] = [];
	const done = new Set<number>([0]);
	const walk = (i: number, from: number) => {
		const leg = legs[i];
		for (let j = from; j < leg.length; j++) {
			const m = leg[j];
			out.push(m);
			for (let k = 1; k < legs.length; k++) {
				if (done.has(k) || legs[k][0] !== m) continue;
				done.add(k);
				walk(k, 1);
				out.push(...legs[k].slice(0, -1).reverse()); // back to where it split off
			}
		}
	};
	if (legs.length) walk(0, 0);
	return out;
}

/** How many maps a route runs (each once, the first not counted). */
export function mapsRun(legs: Legs): number {
	return new Set(legs.flat()).size - 1;
}

/** A route with a map added: past an end of a leg, that leg goes on to it; before the route's first map, the route
 * starts there instead (user: it made a branch); off its side, a branch from the route's map nearest to it (fewest
 * maps). A message when it can't be. */
export function addMap(legs: Legs, node: number, graph: RouteGraph): Legs | string {
	const on = new Set(legs.flat());
	if (on.has(node)) return `Map #${node} is on the route already.`;
	const path = graph.shortest(node, (u) => on.has(u));
	if (!path) return `No known path from the route to map #${node}.`;
	const way = path.reverse(); // from the route's map to the new one
	const at = way[0];
	const leg = legs.findIndex((l) => l[l.length - 1] === at);
	if (leg >= 0) return legs.map((l, i) => (i === leg ? [...l, ...way.slice(1)] : l));
	if (legs[0][0] === at) return [[...way.reverse(), ...legs[0].slice(1)], ...legs.slice(1)];
	return [...legs, way];
}

/** A route with a map taken off: the route's biggest piece left stays, the rest goes with it (at an end, the map
 * alone; nearer one end, that side; a branch, toward its tip; maps added off the side of a map taken off stay when
 * they're the bigger piece, and are the route then: user: the route's first maps couldn't be taken off). A tie keeps
 * the piece with the route's start, then its end. A message when it can't be. */
export function removeMap(legs: Legs, node: number): Legs | string {
	if (!legs.some((l) => l.includes(node))) return `Map #${node} isn't on the route.`;
	// the route as maps joined to the maps before and after them on its legs
	const near = new Map<number, number[]>();
	const link = (a: number, b: number) => near.set(a, [...(near.get(a) ?? []), b]);
	for (const l of legs)
		for (let k = 0; k + 1 < l.length; k++) {
			link(l[k], l[k + 1]);
			link(l[k + 1], l[k]);
		}
	// the pieces left: what each map next to it reaches without passing it
	const pieces: Set<number>[] = [];
	for (const n of near.get(node) ?? []) {
		if (pieces.some((p) => p.has(n))) continue;
		const piece = new Set([n]);
		for (const todo = [n]; todo.length; )
			for (const m of near.get(todo.pop() as number) ?? [])
				if (m !== node && !piece.has(m)) {
					piece.add(m);
					todo.push(m);
				}
		pieces.push(piece);
	}
	const main = legs[0];
	const rank = (p: Set<number>) => [p.size, p.has(main[0]) ? 1 : 0, p.has(main[main.length - 1]) ? 1 : 0];
	const best = pieces.sort((a, b) => {
		const [x, y] = [rank(a), rank(b)];
		return y[0] - x[0] || y[1] - x[1] || y[2] - x[2];
	})[0];
	if (!best) return "A route needs two maps: delete it instead.";
	// each leg's maps in that piece (a run of it: a leg passing the map has a side in another piece); the main leg's
	// first, else the first left; a branch left on its first map alone goes
	const kept = legs.map((l) => l.filter((m) => best.has(m))).filter((l) => l.length);
	const out = tidy([kept[0], ...kept.slice(1).filter((l) => l.length >= 2)]);
	return out[0].length >= 2 ? out : "A route needs two maps: delete it instead.";
}

/** A leg that now ends where a branch starts goes on along that branch (no going there and back for nothing). */
function tidy(legs: Legs): Legs {
	const out = legs.map((l) => [...l]);
	for (let merged = true; merged; ) {
		merged = false;
		for (let i = 0; i < out.length && !merged; i++) {
			const end = out[i][out[i].length - 1];
			const k = out.findIndex((l, n) => n > 0 && n !== i && l[0] === end);
			if (k >= 0) {
				out[i].push(...out[k].slice(1));
				out.splice(k, 1);
				merged = true;
			}
		}
	}
	return out;
}

/** A route to save (Save route, Add / Remove maps): its ends' numbers, how many maps it runs, and per leg its maps'
 * spots and its line. */
export function savedRouteOf(legs: Legs, graph: RouteGraph): SavedRoute {
	const main = legs[0];
	const spots = (l: number[]) => l.map((id) => graph.at(id)).filter((p): p is Point => !!p);
	return {
		from: main[0],
		to: main[main.length - 1],
		maps: mapsRun(legs),
		legs: legs.map((l) => ({
			maps: spots(l).map(([x, y]) => [x, y] as [number, number]),
			line: graph.line(l).map(([x, y]) => [x, y] as [number, number]),
		})),
	};
}
