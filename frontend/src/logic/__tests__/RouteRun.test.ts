import { describe, expect, it } from "vitest";
import { alongLine, DASH_MS, DASHES, dashAt, runLeg } from "@/logic/RouteRun";

describe("RouteRun", () => {
	it("the dashes step on with time and go round", () => {
		expect(dashAt(0)).toBe(DASHES[0]);
		expect(dashAt(DASH_MS * 3 + 1)).toBe(DASHES[3]);
		expect(dashAt(DASH_MS * DASHES.length)).toBe(DASHES[0]);
	});

	it("the runner's leg: tracked, from your map to the next; not tracked, the whole route; one map, none", () => {
		expect(runLeg([1, 2, 3, 4], 1)).toEqual([2, 3]);
		expect(runLeg([1, 2, 3, 4], undefined)).toEqual([1, 2, 3, 4]);
		expect(runLeg([1, 2, 3, 4], 3)).toEqual([]); // (at the end: nowhere left to go)
		expect(runLeg([7], undefined)).toEqual([]);
	});

	it("a point along a line by its length", () => {
		const l: [number, number][] = [
			[0, 0],
			[10, 0],
			[10, 30],
		];
		expect(alongLine(l, 0)).toEqual([0, 0]);
		expect(alongLine(l, 0.25)).toEqual([10, 0]); // (10 of 40)
		expect(alongLine(l, 0.5)).toEqual([10, 10]);
		expect(alongLine(l, 1)).toEqual([10, 30]);
		expect(alongLine(l, 2)).toEqual([10, 30]);
		expect(alongLine([[3, 4]], 0.5)).toEqual([3, 4]);
	});
});
