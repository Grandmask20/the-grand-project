import { describe, expect, it } from "vitest";
import { mapsLeft, nextNew, routeBox, routeTitle, savedRoute, tracking } from "@/hooks/map/UseRoutes";
import { RouteGraph } from "@/logic/Routes";

const graph = new RouteGraph({
	nodes: [
		{ id: 252, x: 0, y: 0, icons: [], status: "confirmed" },
		{ id: 253, x: 100, y: 0, icons: [], status: "confirmed" },
		{ id: 262, x: 100, y: 300, icons: [], status: "confirmed" },
	],
	edges: [
		{ a: 252, b: 253 },
		{ a: 253, b: 262 },
	],
});

describe("routes", () => {
	it("tracking says how many maps are left, then that you're there", () => {
		expect(tracking([252, 253, 262], 0)).toBe("2 maps left");
		expect(tracking([252, 253, 262], 1)).toBe("1 map left");
		expect(tracking([252, 253, 262], 2)).toMatch(/You're there/);
	});

	it("a branch run there and back: the maps on the way back aren't counted or stopped on again", () => {
		const walk = [1, 2, 3, 4, 3, 5, 6]; // 4 is a branch off 3
		expect(tracking(walk, 2)).toBe("3 maps left");
		expect(nextNew(walk, 3)).toBe(5); // from 4 on to 5, past 3
		expect(tracking(walk, 3)).toBe("2 maps left");
		expect(mapsLeft([252, 253, 252, 262], 1)).toBe(1); // (the saved route's row counts the same: CodeRabbit)
		expect(nextNew(walk, 6)).toBeNull();
	});

	it("a saved route keeps its ends, its map count and its line", () => {
		const path = graph.shortest(252, (u) => u === 262) ?? [];
		const r = savedRoute(graph, path);
		const spots: [number, number][] = [
			[0, 0],
			[100, 0],
			[100, 300],
		];
		expect(r).toEqual({ from: 252, to: 262, maps: 2, legs: [{ maps: spots, line: spots }] });
		// (user's format: name, then its ends)
		expect(routeTitle("route1", r)).toBe("route1 (map #252 -> map #262)");
	});

	it("fits a saved route with room round it", () => {
		const [x0, y0, x1, y1] = routeBox({
			from: 252,
			to: 262,
			maps: 2,
			line: [
				[0, 0],
				[100, 0],
				[100, 300],
			],
		});
		expect(x0).toBeLessThan(0);
		expect(y0).toBeLessThan(0);
		expect(x1).toBeGreaterThan(100);
		expect(y1).toBeGreaterThan(300);
		expect(y1 - y0).toBeCloseTo(300 + 2 * 0.12 * 300); // a share of its longest side each way
	});
});
