import { describe, expect, it } from "vitest";
import { Geo } from "@/logic/Geo";

const geo = new Geo({ grid: { x0: -300, y0: -200, scale: 0.5, width: 4000, height: 3000 }, world: 16384, offset: 4096, zmax: 6 });

describe("Geo", () => {
	it("turns atlas points into longitude / latitude and back", () => {
		for (const [x, y] of [
			[0, 0],
			[-300, -200],
			[7000, 5000],
		]) {
			const [lng, lat] = geo.toLngLat(x, y);
			const [bx, by] = geo.toAtlas(lng, lat);
			expect(bx).toBeCloseTo(x, 6);
			expect(by).toBeCloseTo(y, 6);
		}
	});

	it("puts the map image's corner at the world's offset", () => {
		const [lng] = geo.toLngLat(-300, -200);
		expect(lng).toBeCloseTo((4096 / 16384) * 360 - 180, 9);
	});

	it("knows how many screen px an atlas unit is at a zoom", () => {
		const z = geo.zoomFor(1.5);
		expect(geo.pxPerUnit(z)).toBeCloseTo(1.5, 9);
		expect(geo.pxPerUnit(z + 1)).toBeCloseTo(3, 9);
	});

	it("gives image corners clockwise from the top left", () => {
		const [tl, tr, br, bl] = geo.corners([0, 0, 100, 50]);
		expect(tl[0]).toBeLessThan(tr[0]);
		expect(tr[1]).toBeGreaterThan(br[1]); // north is up
		expect(bl[0]).toBe(tl[0]);
	});
});
