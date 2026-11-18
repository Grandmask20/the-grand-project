import { describe, expect, it } from "vitest";
import { cityColours, landmarkColours, rampColour, styleColour, withAlpha } from "@/logic/Colours";
import { meta, style } from "@/test/Fixtures";

describe("Colours", () => {
	it("uses the View tab's colour when it is set", () => {
		expect(styleColour({ ...style, path_col: "#123456" }, "path_col", "#ffffff")).toBe("#123456");
		expect(styleColour({ ...style }, "path_col", "#ffffff")).toBe("#ffffff");
		expect(cityColours(meta, { ...style, city_col_Vaal: "#000001" }).Vaal).toBe("#000001");
		expect(landmarkColours(meta, { ...style }).Tower).toBe("#64eb64");
	});

	it("reads a colour spread and adds alpha", () => {
		expect(rampColour(["#000000", "#ffffff"], 1)).toBe("#ffffff");
		expect(rampColour([], 0.5)).toBe("#ffffff");
		expect(withAlpha("#ff8000", 0.5)).toBe("rgba(255, 128, 0, 0.5)");
	});
});
