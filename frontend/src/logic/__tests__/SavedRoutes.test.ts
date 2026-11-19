import { describe, expect, it } from "vitest";
import { RouteGraph } from "@/logic/Routes";
import {
	addMap,
	legsOf,
	mapsRun,
	nearestOn,
	removeMap,
	routeLines,
	savedRouteOf,
	visitOrder,
} from "@/logic/SavedRoutes";

// your example: 1 - 2 - 3 - 5 - 6 up the middle, 4 off the side of 3; 7 past 6; 8 past 4; 9 alone
const graph = new RouteGraph({
	nodes: [1, 2, 3, 4, 5, 6, 7, 8, 9].map((id) => ({ id, x: id * 100, y: id * 10, icons: [], status: "confirmed" })),
	edges: [
		{ a: 1, b: 2 },
		{ a: 2, b: 3 },
		{ a: 3, b: 5 },
		{ a: 5, b: 6 },
		{ a: 3, b: 4 },
		{ a: 6, b: 7 },
		{ a: 4, b: 8 },
	],
});
const main = [[1, 2, 3, 5, 6]];

describe("saved routes", () => {
	it("goes on past the route's end, and branches off its side", () => {
		expect(addMap(main, 7, graph)).toEqual([[1, 2, 3, 5, 6, 7]]);
		const branched = addMap(main, 4, graph);
		expect(branched).toEqual([
			[1, 2, 3, 5, 6],
			[3, 4],
		]);
		// a map past the branch's end: the branch goes on
		expect(addMap(branched as number[][], 8, graph)).toEqual([
			[1, 2, 3, 5, 6],
			[3, 4, 8],
		]);
	});

	it("runs a branch where it splits off, there and back (1, 2, 3, the branch's 4, then 5 and 6)", () => {
		expect(
			visitOrder([
				[1, 2, 3, 5, 6],
				[3, 4],
			]),
		).toEqual([1, 2, 3, 4, 3, 5, 6]);
		expect(
			visitOrder([
				[1, 2, 3, 5, 6],
				[3, 4, 8],
			]),
		).toEqual([1, 2, 3, 4, 8, 4, 3, 5, 6]);
		expect(
			mapsRun([
				[1, 2, 3, 5, 6],
				[3, 4],
			]),
		).toBe(5);
	});

	it("says why a map can't be added", () => {
		expect(addMap(main, 3, graph)).toBe("Map #3 is on the route already.");
		expect(addMap(main, 9, graph)).toBe("No known path from the route to map #9.");
	});

	it("takes a map off with its shorter side, and the branches off the maps taken off", () => {
		const legs = [
			[1, 2, 3, 5, 6],
			[3, 4, 8],
		];
		// a branch: toward its tip
		expect(removeMap(legs, 8)).toEqual([
			[1, 2, 3, 5, 6],
			[3, 4],
		]);
		expect(removeMap(legs, 4)).toEqual([[1, 2, 3, 5, 6]]);
		// the main leg's end: the map alone
		expect(removeMap(legs, 6)).toEqual([
			[1, 2, 3, 5],
			[3, 4, 8],
		]);
		// nearer the end: that side; the main leg cut back to where the branch starts goes on along the branch
		expect(removeMap(legs, 5)).toEqual([[1, 2, 3, 4, 8]]);
		// nearer the start: that side (user: the route's first maps couldn't be taken off)
		expect(removeMap(legs, 1)).toEqual([
			[2, 3, 5, 6],
			[3, 4, 8],
		]);
		expect(removeMap(legs, 2)).toEqual([
			[3, 5, 6],
			[3, 4, 8],
		]);
	});

	it("your case: two maps added past the end, then the first two taken off one by one", () => {
		const added = [[1, 2, 3, 5]];
		const once = removeMap(added, 1);
		expect(once).toEqual([[2, 3, 5]]);
		expect(removeMap(once as number[][], 2)).toEqual([[3, 5]]);
	});

	it("your case: maps added off the route's side, then the route's own maps taken off: the branch is the route", () => {
		// a route 1 - 2, maps 3 - 5 - 6 added off 2's side as a branch... here 2 - 3 - 5 - 6 (3 is off 2)
		const legs = [
			[1, 2],
			[2, 3, 5, 6],
		];
		expect(removeMap(legs, 1)).toEqual([[2, 3, 5, 6]]);
		expect(removeMap(removeMap(legs, 1) as number[][], 2)).toEqual([[3, 5, 6]]);
	});

	it("maps added off the side of the route's first map stay when that map goes (the bigger piece)", () => {
		const legs = [
			[1, 2],
			[1, 7, 8, 9],
		];
		expect(removeMap(legs, 1)).toEqual([[7, 8, 9]]);
		// a tie keeps the piece with the route's start
		expect(
			removeMap(
				[
					[1, 2, 3, 5, 6],
					[3, 4],
				],
				3,
			),
		).toEqual([[1, 2]]);
	});

	it("keeps at least two maps", () => {
		expect(removeMap([[1, 2]], 1)).toBe("A route needs two maps: delete it instead.");
		expect(removeMap([[1, 2, 3]], 2)).toBe("A route needs two maps: delete it instead.");
		expect(removeMap(main, 9)).toBe("Map #9 isn't on the route.");
	});

	it("a map before the route's first map: the route starts there (it made a branch)", () => {
		// 7 hangs off 6; a route 6 - 5 - 3 starts on 6
		expect(addMap([[6, 5, 3]], 7, graph)).toEqual([[7, 6, 5, 3]]);
	});

	it("takes the route's map nearest a click, when near enough (an icon beside it can belong to another map)", () => {
		expect(nearestOn(main, graph, [310, 30], 20)).toBe(3);
		expect(nearestOn(main, graph, [400, 40], 20)).toBeNull(); // map 4 is beside the route, not on it
	});

	it("is saved by its maps' spots, and found again on the atlas from them", () => {
		const r = savedRouteOf(
			[
				[1, 2, 3, 5, 6],
				[3, 4],
			],
			graph,
		);
		expect(r).toMatchObject({ from: 1, to: 6, maps: 5 });
		expect(r.legs?.[1].maps).toEqual([
			[300, 30],
			[400, 40],
		]);
		expect(routeLines(r)).toHaveLength(2);
		expect(legsOf(r, graph)).toEqual([
			[1, 2, 3, 5, 6],
			[3, 4],
		]);
	});

	it("finds a route saved before routes kept their maps by its line's ends", () => {
		const old = { from: 1, to: 3, maps: 2, line: graph.line([1, 2, 3]) };
		expect(legsOf(old, graph)).toEqual([[1, 2, 3]]);
		expect(routeLines(old)).toEqual([graph.line([1, 2, 3])]);
	});
});
