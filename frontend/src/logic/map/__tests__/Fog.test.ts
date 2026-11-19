import { describe, expect, it } from "vitest";
import { type FogField, fogCells, paintFog } from "@/logic/map/Fog";

/** A field of little-endian uint16 cells. */
function field(values: number[]): FogField {
	const bytes = values.flatMap((v) => [v & 255, v >> 8]);
	return {
		w: values.length,
		h: 1,
		top: 4,
		data: btoa(String.fromCharCode(...bytes)),
		corners: [
			[0, 1],
			[1, 1],
			[1, 0],
			[0, 0],
		],
	};
}

describe("Fog", () => {
	it("reads the cells from base64", () => {
		expect([...fogCells(field([0, 65534, 65535, 300]))]).toEqual([0, 65534, 65535, 300]);
	});

	it("hides what isn't revealed yet, and never where there is no ground", () => {
		const f = field([0, 32767, 65534, 65535]); // steps 0, 2, 4, no ground
		const px = new Uint8ClampedArray(4 * 4);
		paintFog(px, fogCells(f), f.top, 1, false, 4);
		expect([px[3], px[7], px[11], px[15]]).toEqual([0, 255, 255, 0]);
		paintFog(px, fogCells(f), f.top, 4.5, false, 4); // every step shown
		expect([px[3], px[7], px[11]]).toEqual([0, 0, 0]);
	});

	it("fades the area sweep's edge", () => {
		const f = field([32767]); // step 2 of 4
		const px = new Uint8ClampedArray(4);
		paintFog(px, fogCells(f), f.top, 1.96, true, 4); // a soft edge of 0.08 steps
		expect(px[3]).toBeGreaterThan(0);
		expect(px[3]).toBeLessThan(255);
	});
});
