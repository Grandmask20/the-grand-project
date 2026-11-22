import { describe, expect, it } from "vitest";
import { FOG_COLOUR, FOG_RGB, rgb01, SKY } from "@/logic/Sky";

describe("Sky", () => {
	it("a colour as the shaders take it", () => {
		expect(rgb01("#ff8000")).toEqual([1, 128 / 255, 0]);
		expect(FOG_RGB).toEqual(rgb01(FOG_COLOUR));
	});

	it("the sky's haze is the fog the ground and models fade into, and no globe atmosphere", () => {
		expect(SKY["fog-color"]).toBe(FOG_COLOUR);
		expect(SKY["atmosphere-blend"]).toBe(0);
	});
});
