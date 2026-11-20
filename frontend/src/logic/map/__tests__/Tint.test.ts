import { describe, expect, it } from "vitest";
import type { Frames } from "@/domain/replay/Frames";
import type { ReplayPlan } from "@/domain/replay/ReplayPlan";
import { isTintMode, paintTint, TINT_RES, TINT_RES_REPLAY, tintBox } from "@/logic/map/Tint";

const square = (x0: number, y0: number, x1: number, y1: number): [number, number][] => [
	[x0, y0],
	[x1, y0],
	[x1, y1],
	[x0, y1],
];

/** Two screenshots side by side overlapping in the middle: the first older, in session 0; the second in session 1. */
const frames = {
	frames: [
		{ name: "a", corners: square(0, 0, 60, 40), session: 0, rank: 0 },
		{ name: "b", corners: square(40, 0, 100, 40), session: 1, rank: 1 },
	],
	order: [0, 1],
	ramp: ["#000000", "#ffffff"],
	sessions: ["#ff0000", "#00ff00"],
	heat_top: 2,
} as unknown as Frames;

const rgbaAt = (out: Uint8ClampedArray, w: number, x: number, y: number) => [
	...out.slice(4 * (y * w + x), 4 * (y * w + x) + 4),
];

describe("Tint", () => {
	it("knows the Colour by modes it draws", () => {
		expect(isTintMode("times seen")).toBe(true);
		expect(isTintMode("off")).toBe(false);
	});

	it("puts its grid round every screenshot, coarser while replaying", () => {
		const box = tintBox(frames, false);
		expect(box).toMatchObject({ x0: 0, y0: 0, cell: 100 / TINT_RES, w: TINT_RES });
		expect(tintBox(frames, true)?.w).toBe(TINT_RES_REPLAY);
		expect(tintBox({ ...frames, frames: [] }, false)).toBeNull();
	});

	it("colours each spot by the newest screenshot over it", () => {
		const box = { x0: 0, y0: 0, cell: 10, w: 10, h: 4 };
		const out = new Uint8ClampedArray(4 * box.w * box.h);
		paintTint(out, box, frames, "by session", null, Number.POSITIVE_INFINITY, null);
		expect(rgbaAt(out, box.w, 1, 1)).toEqual([255, 0, 0, 255]);
		expect(rgbaAt(out, box.w, 5, 1)).toEqual([0, 255, 0, 255]); // the overlap: the newer one's
		expect(rgbaAt(out, box.w, 8, 1)).toEqual([0, 255, 0, 255]);
	});

	it("counts the screenshots over a spot, and only the revealed ones while replaying", () => {
		const box = { x0: 0, y0: 0, cell: 10, w: 10, h: 4 };
		const out = new Uint8ClampedArray(4 * box.w * box.h);
		paintTint(out, box, frames, "times seen", null, Number.POSITIVE_INFINITY, null);
		expect(rgbaAt(out, box.w, 1, 1)).toEqual([0, 0, 0, 255]); // seen once: the ramp's start
		expect(rgbaAt(out, box.w, 5, 1)).toEqual([255, 255, 255, 255]); // twice: its end
		const plan = { step_of: [0, 1] } as ReplayPlan;
		const early = new Uint8ClampedArray(4 * box.w * box.h);
		paintTint(early, box, frames, "times seen", plan, 0.5, null);
		expect(rgbaAt(early, box.w, 8, 1)[3]).toBe(0); // the second not in yet
	});

	it("leaves out where the map image shows no ground", () => {
		const box = { x0: 0, y0: 0, cell: 10, w: 10, h: 4 };
		const out = new Uint8ClampedArray(4 * box.w * box.h);
		const mask = new Uint8Array(box.w * box.h).fill(1);
		mask[1 * box.w + 1] = 0;
		paintTint(out, box, frames, "oldest to newest", null, Number.POSITIVE_INFINITY, mask);
		expect(rgbaAt(out, box.w, 1, 1)[3]).toBe(0);
		expect(rgbaAt(out, box.w, 2, 1)[3]).toBe(255);
	});
});
