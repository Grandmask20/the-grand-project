import { describe, expect, it } from "vitest";
import { RouteGraph, ringedMaps, routeBetween, routeFromNearestBlue, routeMarks } from "@/logic/Routes";

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

describe("RouteGraph and map node states", () => {
	// 0 - 1 - 2 - 3 straight, 0 - 4 - 5 - 6 - 3 round; 8 next to 0 only; 9 has a Breach past 1, 10 one past 5
	const states: Record<number, string | undefined> = { 0: "green", 1: "green", 8: "green", 2: "red", 4: "grey" };
	const g = new RouteGraph({
		nodes: [
			...[0, 1, 2, 3, 4, 5, 6, 8].map((id) => ({
				id,
				x: id * 100,
				y: 0,
				icons: [],
				status: "confirmed",
				...(states[id] !== undefined ? { state: states[id] } : {}),
			})),
			{ id: 9, x: 100, y: 100, icons: ["Breach"], status: "confirmed", state: "red" },
			{ id: 10, x: 500, y: 100, icons: ["Breach"], status: "confirmed", state: "blue" },
			{ id: 11, x: 900, y: 0, icons: [], status: "confirmed", state: "" },
		],
		edges: [
			{ a: 0, b: 1 },
			{ a: 1, b: 2 },
			{ a: 2, b: 3 },
			{ a: 0, b: 4 },
			{ a: 4, b: 5 },
			{ a: 5, b: 6 },
			{ a: 6, b: 3 },
			{ a: 8, b: 0 },
			{ a: 1, b: 9 },
			{ a: 5, b: 10 },
			{ a: 3, b: 11 },
		],
	});

	it("goes round green and red maps (user's rule), from a green start; grey, blue and unnamed maps carry it", () => {
		expect(g.shortest(0, (u) => u === 3, { runnable: true })).toEqual([0, 4, 5, 6, 3]);
		expect(g.shortest(0, (u) => u === 11, { runnable: true })).toEqual([0, 4, 5, 6, 3, 11]);
	});

	it("never ends on a green or red map; asked for every map (Adjust route), it goes through them", () => {
		expect(g.shortest(0, (u) => u === 2, { runnable: true })).toBeNull();
		expect(g.shortest(0, (u) => u === 3)).toEqual([0, 1, 2, 3]);
	});

	it("a start with only green maps round it finds nothing", () => {
		expect(g.shortest(8, (u) => u === 3, { runnable: true })).toBeNull();
	});

	it("the nearest map with an icon that can still be run", () => {
		expect(g.shortest(0, (u) => g.iconsOf(u).includes("Breach"))).toEqual([0, 1, 9]);
		expect(g.shortest(0, (u) => g.iconsOf(u).includes("Breach"), { runnable: true })).toEqual([0, 4, 5, 10]);
	});

	it("avoids the maps asked, with the states too", () => {
		expect(g.shortest(0, (u) => u === 3, { avoid: new Set([5]) })).toEqual([0, 1, 2, 3]);
		expect(g.shortest(0, (u) => u === 3, { avoid: new Set([5]), runnable: true })).toBeNull();
	});

	it("says why a map can't be run", () => {
		expect(g.closed(1)).toBe("green (cleared)");
		expect(g.closed(2)).toBe("red (failed)");
		for (const id of [3, 4, 10, 11, 42]) expect(g.closed(id)).toBeNull();
		expect(g.closedNote(2)).toBe("Map #2 is red (failed): it can't be run again.");
		expect(g.closedNote(4)).toBeNull();
	});

	it("routeBetween: from any start round green and red maps, or why there is none", () => {
		expect(routeBetween(g, 0, 3)).toEqual([0, 4, 5, 6, 3]);
		expect(routeBetween(g, 2, 2)).toEqual([2]); // you are there, whatever its state
		expect(routeBetween(g, 4, 1)).toBe("Map #1 is green (cleared): it can't be run again.");
		expect(routeBetween(g, 0, 9)).toBe("Map #9 is red (failed): it can't be run again.");
		expect(routeBetween(g, 8, 3)).toBe("No path from map #8 to map #3 over maps that can still be run (grey / blue).");
	});
});

describe("routeFromNearestBlue", () => {
	// the map clicked, 0 (grey): 0 - 1 - 2 (blue) far off in distance; 0 - 3 - 4 - 5 (blue) close by but a map more;
	// 0 - 6 (red) - 7 (blue) one map away behind a failed map; 8 (green) - 9 (blue); 10 (grey) alone
	const S: Record<number, string> = {
		0: "grey",
		1: "grey",
		2: "blue",
		3: "",
		4: "grey",
		5: "blue",
		6: "red",
		7: "blue",
	};
	const g = new RouteGraph({
		nodes: [
			...[0, 1, 2, 3, 4, 5, 6, 7].map((id) => ({
				id,
				x: [0, 1, 2].includes(id) ? id * 5000 : id * 10,
				y: 0,
				icons: [],
				status: "confirmed",
				state: S[id],
			})),
			{ id: 8, x: 0, y: 900, icons: [], status: "confirmed", state: "green" },
			{ id: 9, x: 0, y: 950, icons: [], status: "confirmed", state: "blue" },
			{ id: 10, x: 900, y: 900, icons: [], status: "confirmed" },
		],
		edges: [
			{ a: 0, b: 1 },
			{ a: 1, b: 2 },
			{ a: 0, b: 3 },
			{ a: 3, b: 4 },
			{ a: 4, b: 5 },
			{ a: 0, b: 6 },
			{ a: 6, b: 7 },
			{ a: 8, b: 9 },
		],
	});

	it("from the blue map the fewest maps away (not the nearest in distance), never through a red one", () => {
		expect(routeFromNearestBlue(g, 0)).toEqual([2, 1, 0]);
		expect(routeFromNearestBlue(g, 4)).toEqual([5, 4]);
	});

	it("a blue map clicked is its own nearest", () => {
		expect(routeFromNearestBlue(g, 5)).toEqual([5]);
	});

	it("says why there is none", () => {
		expect(routeFromNearestBlue(g, 8)).toBe("Map #8 is green (cleared): it can't be run again.");
		expect(routeFromNearestBlue(g, 6)).toBe("Map #6 is red (failed): it can't be run again.");
		expect(routeFromNearestBlue(g, 10)).toBe(
			"No blue map leads to map #10 over maps that can still be run (grey / blue).",
		);
	});

	it("knows each map's state", () => {
		expect(g.stateOf(2)).toBe("blue");
		expect(g.stateOf(3)).toBe("");
		expect(g.stateOf(10)).toBe(""); // none sent
		expect(g.stateOf(42)).toBe("");
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
