import { describe, expect, it } from "vitest";
import { OWN_IMAGES, squareImage } from "@/logic/map/Pictures";

describe("Pictures", () => {
	it("squares are hollow, or filled", () => {
		const hollow = squareImage();
		const filled = squareImage(true);
		expect(hollow.width).toBe(32);
		expect(hollow.data.length).toBe(32 * 32 * 4);
		const alphaAt = (img: { data: Uint8Array }, x: number, y: number) => img.data[(y * 32 + x) * 4 + 3];
		expect(alphaAt(hollow, 16, 16)).toBe(0);
		expect(alphaAt(filled, 16, 16)).toBe(255);
		expect(alphaAt(hollow, 4, 16)).toBe(255);
		expect(alphaAt(hollow, 1, 16)).toBe(0); // a clear edge around the ring
	});

	it("knows the map's own pictures apart from icons'", () => {
		expect(OWN_IMAGES.has("node-picture")).toBe(true);
		expect(OWN_IMAGES.has("LostTower")).toBe(false);
	});
});
