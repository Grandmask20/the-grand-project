import type { Graph } from "@/domain/map/Graph";
import type { Point } from "./Geo";

/** The maps of a route shown that get a ring: every map but the first (your position's marker is there), or the first
 * alone while the route's last map is being picked (user: nothing showed until the second map). */
export function ringedMaps(path: number[]): number[] {
	return path.length === 1 ? path : path.slice(1);
}

/** A route's marks on the map: its maps ringed, and while it is tracked (`at`) the map you are on marked instead, and
 * only the maps not run yet ringed. */
export function routeMarks(path: number[], at?: number): { rings: number[]; here: number | null } {
	if (at === undefined) return { rings: ringedMaps(path), here: null };
	const run = new Set(path.slice(0, at + 1));
	return { rings: [...new Set(path.slice(at + 1).filter((m) => !run.has(m)))], here: path[at] ?? null };
}

/** The route from `from` to `to` (fewest maps) over maps that can still be run, or why there is none: it starts on
 * `from` whatever its state (you are there), then passes grey and blue maps only (user's rule: green and red maps
 * can't be run again). */
export function routeBetween(graph: RouteGraph, from: number, to: number): number[] | string {
	if (from === to) return [to];
	const shut = graph.closedNote(to);
	if (shut) return shut;
	return (
		graph.shortest(from, (u) => u === to, { runnable: true }) ??
		`No path from map #${from} to map #${to} over maps that can still be run (grey / blue).`
	);
}

/** The route to `node` from the blue map the fewest maps away (Route here from nearest map: the game lets you start
 * any blue map), blue map first, over maps that can still be run; or why there is none. The map clicked when blue is
 * its own nearest one. */
export function routeFromNearestBlue(graph: RouteGraph, node: number): number[] | string {
	const shut = graph.closedNote(node);
	if (shut) return shut;
	if (graph.stateOf(node) === ROUTE_START_STATE) return [node];
	// from the map clicked outward (paths go both ways: the same maps as from the blue map)
	const path = graph.shortest(node, (u) => graph.stateOf(u) === ROUTE_START_STATE, { runnable: true });
	return path ? path.reverse() : `No blue map leads to map #${node} over maps that can still be run (grey / blue).`;
}

/** How a route is looked for: never through the maps in `avoid`; `runnable`: only over maps that can still be run
 * (never onto a green or red map, ROUTE_CLOSED; the start is allowed whatever its state: you are there). */
export interface RouteOptions {
	avoid?: Set<number>;
	runnable?: boolean;
}

/** The maps and paths routes are found on: every map run costs 1 (fewest maps), the length only breaks ties. */
export class RouteGraph {
	private readonly adj = new Map<number, number[]>();
	private readonly pos = new Map<number, Point>();
	private readonly icons = new Map<number, string[]>();
	private readonly states = new Map<number, string>();
	private readonly lines = new Map<string, Point[]>();

	constructor(graph: Graph) {
		for (const n of graph.nodes) {
			this.adj.set(n.id, []);
			this.pos.set(n.id, [n.x, n.y]);
			this.icons.set(n.id, n.icons);
			this.states.set(n.id, n.state ?? "");
		}
		for (const e of graph.edges) {
			if (e.a === e.b || !this.adj.has(e.a) || !this.adj.has(e.b)) continue;
			this.adj.get(e.a)?.push(e.b);
			this.adj.get(e.b)?.push(e.a);
			if (e.line) this.lines.set(`${e.a}-${e.b}`, e.line);
		}
	}

	has(id: number): boolean {
		return this.adj.has(id);
	}

	at(id: number): Point | undefined {
		return this.pos.get(id);
	}

	iconsOf(id: number): string[] {
		return this.icons.get(id) ?? [];
	}

	/** A map's state (grey / blue / green / red), "" when no screenshot named it. */
	stateOf(id: number): string {
		return this.states.get(id) ?? "";
	}

	/** Why a route can't run a map (its state's words: green, cleared; red, failed), or null when it can (grey, blue,
	 * or no state named). */
	closed(id: number): string | null {
		return ROUTE_CLOSED[this.states.get(id) ?? ""] ?? null;
	}

	/** What the page says when a route is asked to a map that can't be run again, or null when it can be. */
	closedNote(id: number): string | null {
		const why = this.closed(id);
		return why ? `Map #${id} is ${why}: it can't be run again.` : null;
	}

	/** The map closest to a point. */
	nearest(x: number, y: number): number | null {
		let best: number | null = null;
		let bd = Number.POSITIVE_INFINITY;
		for (const [id, [px, py]] of this.pos) {
			const d = (px - x) ** 2 + (py - y) ** 2;
			if (d < bd) {
				bd = d;
				best = id;
			}
		}
		return best;
	}

	/** The route from `from` (one map, or the nearest of several) to the first map `done` accepts (fewest maps), or
	 * null; as `opts` asks (RouteOptions). */
	shortest(from: number | number[], done: (id: number) => boolean, opts: RouteOptions = {}): number[] | null {
		const { avoid, runnable } = opts;
		const starts = new Set((Array.isArray(from) ? from : [from]).filter((s) => this.adj.has(s)));
		if (!starts.size) return null;
		const cost = new Map<number, number>();
		const prev = new Map<number, number>();
		const heap = new MinHeap();
		for (const s of starts) {
			cost.set(s, 0);
			heap.push(0, s);
		}
		while (heap.size) {
			const [c, u] = heap.pop();
			if (c > (cost.get(u) ?? Number.POSITIVE_INFINITY)) continue;
			if (!starts.has(u) && done(u)) {
				const path = [u];
				for (let v = prev.get(u); v !== undefined; v = prev.get(v)) path.push(v);
				return path.reverse();
			}
			for (const v of this.adj.get(u) ?? []) {
				if (avoid?.has(v) || (runnable && this.closed(v))) continue;
				// a map run outweighs any distance (1e-6 x distance could pass a whole map on a big atlas: CodeRabbit)
				const nc = c + ROUTE_HOP + this.dist(u, v);
				if (nc < (cost.get(v) ?? Number.POSITIVE_INFINITY)) {
					cost.set(v, nc);
					prev.set(v, u);
					heap.push(nc, v);
				}
			}
		}
		return null;
	}

	/** A route's line in atlas units, along curved paths where the app traced them. */
	line(path: number[]): Point[] {
		const out: Point[] = [];
		for (let i = 0; i + 1 < path.length; i++) {
			const [a, b] = [path[i], path[i + 1]];
			const fwd = this.lines.get(`${a}-${b}`);
			const back = this.lines.get(`${b}-${a}`);
			const pa = this.pos.get(a) as Point;
			const pb = this.pos.get(b) as Point;
			const seg = fwd ?? (back ? [...back].reverse() : [pa, pb]);
			out.push(...(out.length ? seg.slice(1) : seg));
		}
		return out;
	}

	private dist(a: number, b: number): number {
		const p = this.pos.get(a) as Point;
		const q = this.pos.get(b) as Point;
		return Math.hypot(p[0] - q[0], p[1] - q[1]);
	}
}

/** A binary min-heap of (cost, id). */
class MinHeap {
	private readonly items: [number, number][] = [];

	get size(): number {
		return this.items.length;
	}

	push(cost: number, id: number): void {
		const a = this.items;
		a.push([cost, id]);
		let i = a.length - 1;
		while (i > 0) {
			const p = (i - 1) >> 1;
			if (a[p][0] <= a[i][0]) break;
			[a[p], a[i]] = [a[i], a[p]];
			i = p;
		}
	}

	pop(): [number, number] {
		const a = this.items;
		const top = a[0];
		const last = a.pop() as [number, number];
		if (a.length) {
			a[0] = last;
			let i = 0;
			for (;;) {
				const l = 2 * i + 1;
				const r = l + 1;
				let m = i;
				if (l < a.length && a[l][0] < a[m][0]) m = l;
				if (r < a.length && a[r][0] < a[m][0]) m = r;
				if (m === i) break;
				[a[m], a[i]] = [a[i], a[m]];
				i = m;
			}
		}
		return top;
	}
}

/** The map node states a route can't run or pass, and their words (user's rule: green maps are cleared and red ones
 * failed, neither can be run again; grey and blue ones can: a grey map turns blue once a map next to it is run). */
const ROUTE_CLOSED: Record<string, string> = { green: "green (cleared)", red: "red (failed)" };
/** The map node state the game lets you start a map from anywhere (Route here from nearest map starts on one). */
const ROUTE_START_STATE = "blue";
/** One map run's cost: more than any route's whole distance in atlas units, so distance only breaks ties. */
const ROUTE_HOP = 1e12;
