import { describe, expect, it } from "vitest";
import { placeLabels } from "@/logic/Labels";

const label = (key: string, x: number, y: number, priority: number) => ({ key, x, y, text: key, colour: "#fff", priority });

describe("placeLabels", () => {
	it("keeps the most important of two that would overlap", () => {
		const got = placeLabels([label("icon", 100, 100, 1), label("city", 104, 100, 3)], 800, 600);
		expect(got.map((l) => l.key)).toEqual(["city"]);
	});

	it("keeps labels apart from each other", () => {
		const got = placeLabels([label("a", 100, 100, 1), label("b", 400, 100, 1)], 800, 600);
		expect(got).toHaveLength(2);
		expect(got[0].top).toBeLessThan(100); // above its anchor
	});

	it("leaves out labels off the screen and stops at the most allowed", () => {
		expect(placeLabels([label("far", -500, -500, 1)], 800, 600)).toEqual([]);
		const many = Array.from({ length: 50 }, (_, i) => label(`l${i}`, 50 + (i % 10) * 70, 40 + Math.floor(i / 10) * 40, 1));
		expect(placeLabels(many, 800, 600, 10)).toHaveLength(10);
	});
});
