import { describe, expect, it } from "vitest";
import type { Frames } from "@/domain/replay/Frames";
import type { ReplayPlan } from "@/domain/replay/ReplayPlan";
import { cameraTarget, counts, ease, fogBands, revealed, seekAt, stepFrom, stepsPerSecond } from "@/logic/Replay";
import { meta } from "@/test/Fixtures";

const plan: ReplayPlan = {
	settings: { ...meta.replay.defaults, length: 10, speed: 2 },
	n_steps: 4,
	kind: "by time",
	area: false,
	step_of: [0, 1, 2, 3],
	ticks: [0, 2],
	step_time: ["01 Jan 12:00", "01 Jan 12:01", "01 Jan 18:00", "01 Jan 18:02"],
	step_session: [0, 0, 1, 1],
	real: "3 min",
	real_seconds: 180,
	frame: null,
	step_key: null,
	maps_at: [3, 5, 9, 15],
	bounds: [0, 0, 2000, 1000],
};

const frames: Frames = {
	frames: [0, 1, 2, 3].map((k) => ({
		name: `f${k}`,
		corners: [
			[k * 500, 0],
			[k * 500 + 400, 0],
			[k * 500 + 400, 300],
			[k * 500, 300],
		],
		session: k < 2 ? 0 : 1,
		rank: k / 3,
		time: null,
	})),
	order: [0, 1, 2, 3],
	ramp: [],
	sessions: [],
	legend: [],
	oldest: "",
	newest: "",
	alpha: 0.3,
	heat_top: 1,
};

describe("Replay", () => {
	it("plays the whole replay in its length at 1x", () => {
		expect(stepsPerSecond(plan)).toBeCloseTo((4 / 10) * 2);
	});

	it("eases the camera, or jumps with smoothing off", () => {
		expect(ease(meta, "off", 0.04)).toBe(1);
		const k = ease(meta, "light", 0.04);
		expect(k).toBeGreaterThan(0);
		expect(k).toBeLessThan(1);
	});

	it("covers the ground not revealed yet with the right fog bands", () => {
		expect(fogBands(0, 4, 4)).toEqual({ full: 1, fading: 0, fade: 0 });
		expect(fogBands(2.5, 4, 4)).toEqual({ full: 3, fading: 2, fade: 0.5 });
	});

	it("seeks, steps and counts", () => {
		expect(seekAt(150, 100, 200, 4)).toBe(1);
		expect(stepFrom(1.5, 1, plan)).toBe(2);
		expect(stepFrom(1.5, -1, plan)).toBe(1);
		expect(stepFrom(0, -1, plan)).toBe(0);
		expect(counts(plan, 2)).toEqual({ shots: 2, maps: 5, when: "01 Jan 12:01", session: 0 });
		expect(revealed(plan, 3, 2)).toBe(false);
		expect(revealed(null, 3, 0)).toBe(true);
	});

	it("points the camera where its setting says", () => {
		expect(cameraTarget(meta, plan, frames, 2)).toEqual(plan.bounds);
		const grow = cameraTarget(meta, { ...plan, settings: { ...plan.settings, camera: "grow with atlas" } }, frames, 2);
		expect(grow?.[2]).toBeLessThan(1100); // only the first two screenshots, and a margin
		const follow = cameraTarget(meta, { ...plan, settings: { ...plan.settings, camera: "follow newest" } }, frames, 3);
		expect(follow && (follow[0] + follow[2]) / 2).toBeCloseTo(1200); // the third screenshot's middle
	});
});
