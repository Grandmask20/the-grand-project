import { describe, expect, it } from "vitest";
import { groundAhead } from "@/components/map/MapTiles";

describe("groundAhead", () => {
	it("lists the zoomed-out ground tiles, coarsest first, within the cap", () => {
		const urls = groundAhead("t/{z}/{x}/{y}.jpg", [
			[-60, -40],
			[60, 40],
		]);
		expect(urls[0]).toBe("t/0/0/0.jpg");
		expect(urls.slice(1, 5)).toEqual(["t/1/0/0.jpg", "t/1/1/0.jpg", "t/1/0/1.jpg", "t/1/1/1.jpg"]);
		expect(urls.length).toBeLessThanOrEqual(340);
		const levels = urls.map((u) => Number(u.split("/")[1]));
		expect(levels).toEqual([...levels].sort((a, b) => a - b)); // whole levels, coarsest first
	});
});
