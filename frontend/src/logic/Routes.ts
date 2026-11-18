import type { Graph } from "@/domain/map/Graph";
import type { Point } from "./Geo";

/** The maps and paths routes are found on: every map run costs 1 (fewest maps), the length only breaks ties. */
export class RouteGraph {
	private readonly adj = new Map<number, number[]>();
	private readonly pos = new Map<number, Point>();
	private readonly icons = new Map<number, string[]>();
	private readonly lines = new Map<string, Point[]>();

	constructor(graph: Graph) {
		for (const n of graph.nodes) {
			this.adj.set(n.id, []);
			this.pos.set(n.id, [n.x, n.y]);
			this.icons.set(n.id, n.icons);
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

	/** The route from `from` to the first map `done` accepts (fewest maps), or null. */
	shortest(from: number, done: (id: number) => boolean): number[] | null {
		if (!this.adj.has(from)) return null;
		const cost = new Map<number, number>([[from, 0]]);
		const prev = new Map<number, number>();
		const heap = new MinHeap();
		heap.push(0, from);
		while (heap.size) {
			const [c, u] = heap.pop();
			if (c > (cost.get(u) ?? Number.POSITIVE_INFINITY)) continue;
			if (u !== from && done(u)) {
				const path = [u];
				for (let v = prev.get(u); v !== undefined; v = prev.get(v)) path.push(v);
				return path.reverse();
			}
			for (const v of this.adj.get(u) ?? []) {
				const nc = c + 1 + 1e-6 * this.dist(u, v);
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
