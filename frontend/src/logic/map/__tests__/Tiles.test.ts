import { describe, expect, it } from "vitest";
import { backdropVersion, groundAhead } from "@/logic/map/Tiles";

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

describe("backdropVersion (the ground under the map's own)", () => {
	it("keeps the ground from before a job's changes while it runs (user: old terrain until the new is in)", () => {
		expect(backdropVersion("r.3-5", "r.3-6", true)).toBe("r.3-5");
	});

	it("follows the current ground once no job runs", () => {
		expect(backdropVersion("r.3-5", "r.3-6", false)).toBe("r.3-6");
	});

	it("never keeps another atlas's ground, even mid-job", () => {
		expect(backdropVersion("r.3-5", "r.4-1", true)).toBe("r.4-1");
	});
});
