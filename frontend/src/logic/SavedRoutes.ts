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

/** The map at a saved spot: the nearest, when it is within ROUTE_SPOT_REACH (a map gone from the atlas isn't stood
 * in for by another one further off: CodeRabbit, a route tracked as another one). */
function mapAt(graph: RouteGraph, x: number, y: number): number | null {
	const id = graph.nearest(x, y);
	const p = id !== null ? graph.at(id) : undefined;
	return p && Math.hypot(p[0] - x, p[1] - y) <= ROUTE_SPOT_REACH ? id : null;
}

/** A saved route's legs on the atlas as it is now: its maps' spots to the maps there (one saved before routes kept
 * their maps: the route between its line's ends). Null when they aren't all on this atlas any more. */
export function legsOf(r: SavedRoute, graph: RouteGraph): Legs | null {
	if (r.legs) {
		const legs: Legs = [];
		for (const leg of r.legs) {
			const ids: number[] = [];
			for (const [x, y] of leg.maps) {
				const id = mapAt(graph, x, y);
				if (id === null) return null;
				if (ids[ids.length - 1] !== id) ids.push(id);
			}
			legs.push(ids);
		}
		return legs[0]?.length >= 2 ? legs.filter((l, i) => i === 0 || l.length >= 2) : null;
	}
	const line = r.line ?? [];
	if (line.length < 2) return null;
	const [a, b] = [line[0], line[line.length - 1]].map(([x, y]) => mapAt(graph, x, y));
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

/** A route with a map taken off. The route's biggest piece left stays (a tie: the piece with the route's start, then
 * its end): at an end the map goes alone, and maps added off the side of a map taken off stay when they're the bigger
 * piece, and are the route then (user: the route's first maps couldn't be taken off). The other pieces join the route
 * again by the shortest way round the map taken off (user: taking a map off cut off the maps after it, though a path
 * led to them from the route), when that way adds no more maps than the piece keeps (else, a stray map would bring a
 * long detour); a piece no way joins goes. Without `graph`, no piece joins again. A message when it can't be. */
export function removeMap(legs: Legs, node: number, graph?: RouteGraph): Legs | string {
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
	const out = [kept[0], ...kept.slice(1).filter((l) => l.length >= 2)];
	if (graph) {
		const on = new Set(best);
		const waiting = pieces.filter((p) => p !== best); // (biggest first)
		for (const piece of waiting) {
			// from whichever of its maps is nearest (CodeRabbit: only the one by the gap was tried), round the map taken
			// off and the pieces not joined yet (the ones joined are the route now: CodeRabbit)
			const avoid = new Set([node]);
			for (const p of waiting) if (p !== piece && ![...p].some((m) => on.has(m))) for (const m of p) avoid.add(m);
			const way = graph.shortest([...piece], (u) => on.has(u), avoid);
			if (!way || way.length - 2 > piece.size) continue;
			const own = treeLegs(way[0], near, piece);
			out.push([...way.reverse(), ...own[0].slice(1)], ...own.slice(1));
			for (const m of [...way, ...piece]) on.add(m);
		}
	}
	const done = tidy(out);
	return done[0].length >= 2 ? done : "A route needs two maps: delete it instead.";
}

/** A piece of a route as legs from one of its maps: each leg goes on to the bigger part, the others branch off. */
function treeLegs(root: number, near: Map<number, number[]>, within: Set<number>): Legs {
	const seen = new Set([root]);
	const sizeOf = (u: number, from: number): number => {
		let n = 1;
		for (const v of near.get(u) ?? []) if (v !== from && within.has(v)) n += sizeOf(v, u);
		return n;
	};
	const out: Legs = [];
	const walk = (leg: number[]) => {
		out.push(leg);
		const branches: number[][] = [];
		for (let u = leg[leg.length - 1]; ; ) {
			const next = (near.get(u) ?? []).filter((v) => within.has(v) && !seen.has(v));
			if (!next.length) break;
			for (const v of next) seen.add(v);
			const at = u;
			next.sort((a, b) => sizeOf(b, at) - sizeOf(a, at));
			for (const v of next.slice(1)) branches.push([at, v]);
			leg.push(next[0]);
			u = next[0];
		}
		for (const b of branches) walk(b);
	};
	walk([root]);
	return out;
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

/** How far (atlas units) a saved map's spot may be from the map found there (as a bookmark's same spot, SAME_SPOT in
 * the app: a rebuild moves maps a little, another map is further). */
const ROUTE_SPOT_REACH = 28;
