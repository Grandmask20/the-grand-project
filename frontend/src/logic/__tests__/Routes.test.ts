import { describe, expect, it } from "vitest";
import { RouteGraph } from "@/logic/Routes";

// 0 - 1 - 2 - 3, and a long way round 0 - 4 - 5 - 6 - 3; 7 alone; map 5 has a Breach
const graph = new RouteGraph({
	nodes: [
		{ id: 0, x: 0, y: 0, icons: [], status: "confirmed" },
		{ id: 1, x: 100, y: 0, icons: [], status: "confirmed" },
		{ id: 2, x: 200, y: 0, icons: [], status: "confirmed" },
		{ id: 3, x: 300, y: 0, icons: ["Ritual"], status: "confirmed" },
		{ id: 4, x: 0, y: 100, icons: [], status: "confirmed" },
		{ id: 5, x: 100, y: 100, icons: ["Breach"], status: "confirmed" },
		{ id: 6, x: 200, y: 100, icons: [], status: "confirmed" },
		{ id: 7, x: 900, y: 900, icons: ["Breach"], status: "confirmed" },
	],
	edges: [
		{ a: 0, b: 1 },
		{
			a: 1,
			b: 2,
			line: [
				[100, 0],
				[150, 30],
				[200, 0],
			],
		},
		{ a: 2, b: 3 },
		{ a: 0, b: 4 },
		{ a: 4, b: 5 },
		{ a: 5, b: 6 },
		{ a: 6, b: 3 },
	],
});

describe("RouteGraph", () => {
	it("takes the fewest maps", () => {
		expect(graph.shortest(0, (u) => u === 3)).toEqual([0, 1, 2, 3]);
	});

	it("finds the nearest map with an icon", () => {
		expect(graph.shortest(0, (u) => graph.iconsOf(u).includes("Breach"))).toEqual([0, 4, 5]);
	});

	it("says when there is no way", () => {
		expect(graph.shortest(0, (u) => u === 7)).toBeNull();
		expect(graph.shortest(42, () => true)).toBeNull();
	});

	it("follows curved paths, either way round", () => {
		expect(graph.line([1, 2])).toEqual([
			[100, 0],
			[150, 30],
			[200, 0],
		]);
		expect(graph.line([3, 2, 1])).toEqual([
			[300, 0],
			[200, 0],
			[150, 30],
			[100, 0],
		]);
	});

	it("finds the closest map", () => {
		expect(graph.nearest(190, 90)).toBe(6);
	});
});
