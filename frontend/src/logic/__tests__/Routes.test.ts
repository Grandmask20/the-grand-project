import { describe, expect, it } from "vitest";
import { RouteGraph, ringedMaps, routeMarks } from "@/logic/Routes";

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
	it("names the maps a path joins straight to one", () => {
		expect(graph.neighbours(0)).toContain(1);
		expect(graph.neighbours(12345)).toEqual([]);
	});

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

	it("takes fewer maps over a shorter distance, on a big atlas too (CodeRabbit)", () => {
		// A to T: two maps through far-away B, or three through nearby C and D
		const g = new RouteGraph({
			nodes: [
				{ id: 0, x: 0, y: 0, icons: [], status: "confirmed" },
				{ id: 1, x: 600000, y: 0, icons: [], status: "confirmed" },
				{ id: 2, x: 0, y: 100, icons: [], status: "confirmed" },
				{ id: 3, x: 0, y: 30, icons: [], status: "confirmed" },
				{ id: 4, x: 0, y: 60, icons: [], status: "confirmed" },
			],
			edges: [
				{ a: 0, b: 1 },
				{ a: 1, b: 2 },
				{ a: 0, b: 3 },
				{ a: 3, b: 4 },
				{ a: 4, b: 2 },
			],
		});
		expect(g.shortest(0, (u) => u === 2)).toEqual([0, 1, 2]);
	});
});

describe("ringedMaps", () => {
	it("rings a route's first map alone while its last is picked, then every map but the first", () => {
		expect(ringedMaps([4])).toEqual([4]);
		expect(ringedMaps([4, 5, 6])).toEqual([5, 6]);
	});

	it("while tracked: the map you are on marked, only the maps not run yet ringed (a branch's way back too)", () => {
		expect(routeMarks([1, 2, 3, 4, 3, 5], 3)).toEqual({ rings: [5], here: 4 });
		expect(routeMarks([1, 2, 3])).toEqual({ rings: [2, 3], here: null });
	});
});
