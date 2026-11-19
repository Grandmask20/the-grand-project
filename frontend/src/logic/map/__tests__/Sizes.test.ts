import { describe, expect, it } from "vitest";
import { Geo } from "@/logic/Geo";
import { iconMinZoom, iconPx, iconSize, nodeRadius, ringRadius, worldSize, zoomAt } from "@/logic/map/Sizes";
import { mapInfo as info } from "@/test/Fixtures";

const geo = new Geo(info);

describe("Sizes", () => {
	it("worldSize grows with the map from its smallest size, and stops at the cap", () => {
		const grow = worldSize(geo, 2, 1) as unknown[];
		expect(grow[0]).toBe("interpolate");
		expect(grow[4]).toBe(1);
		const capped = worldSize(geo, 2, 1, 1.6) as unknown[];
		expect(capped.at(-1)).toBeCloseTo(3.2);
		expect(worldSize(geo, 2, 10, 1)).toBe(10); // the cap under the smallest size: a fixed size
	});

	it("map nodes are dots zoomed out, then grow with the size setting", () => {
		const r1 = nodeRadius(geo, 1) as unknown[];
		const r2 = nodeRadius(geo, 2) as unknown[];
		expect(r1[4]).toBe(2.2); // the dots
		expect(r2.at(-1)).toBe(26);
		expect(r1.at(-1)).toBe(13);
	});

	it("rings grow from 4 px past a node to 16", () => {
		expect(ringRadius(geo, 10)).toEqual([
			"interpolate",
			["exponential", 2],
			["zoom"],
			zoomAt(geo, 0.25),
			14,
			zoomAt(geo, 1.6),
			26,
		]);
	});

	it("icons start where they are big enough and scale with the ground", () => {
		const z0 = iconMinZoom(geo, info);
		expect(z0).toBeLessThanOrEqual(info.maxzoom - 0.5);
		expect(iconPx(geo, info, z0, 1)).toBeCloseTo(info.sprite.min_px, 0);
		const size = iconSize(geo, info, 1) as unknown[];
		expect(size[3]).toBe(z0);
		expect(iconPx(geo, info, z0 + 1, 2)).toBeCloseTo(4 * iconPx(geo, info, z0, 1));
	});
});
