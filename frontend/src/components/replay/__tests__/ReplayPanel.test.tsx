import { act, screen, waitFor } from "@testing-library/react";
import type { Map as MapLibreMap } from "maplibre-gl";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ReplayPanel } from "@/components/replay/ReplayPanel";
import type { ReplayPlan } from "@/domain/replay/ReplayPlan";
import { useAppStore } from "@/store/AppStore";
import { meta } from "@/test/Fixtures";
import { renderWithApp, resetStore } from "@/test/RenderWithApp";

vi.mock("@/utils/Download", () => ({ download: vi.fn() }));

const settings = {
	type: "by time",
	reveal: "screenshots",
	camera: "whole atlas",
	smoothing: Object.keys(meta.replay.smoothing)[0],
	length: 30,
	per_step: 1,
	speed: 1,
	video_width: 1280,
};
const plan = (length: number) =>
	({
		n_steps: 4,
		settings: { ...settings, length },
		kind: "add",
		area: false,
		step_of: [],
		ticks: [],
		step_time: [],
		step_session: [],
		real: "",
		real_seconds: 0,
		frame: null,
		step_key: null,
		maps_at: [0, 1, 2, 3],
		bounds: [0, 0, 100, 100],
	}) as unknown as ReplayPlan;

/** A screen recorder that only remembers being stopped. */
class FakeRecorder {
	static isTypeSupported = () => true;
	static last: FakeRecorder | null = null;
	state = "inactive";
	stops = 0;
	ondataavailable: ((e: { data: Blob }) => void) | null = null;
	onstop: (() => void) | null = null;
	constructor() {
		FakeRecorder.last = this;
	}
	start() {
		this.state = "recording";
	}
	stop() {
		if (this.state !== "recording") throw new Error("stopped twice");
		this.state = "inactive";
		this.stops++;
		this.onstop?.();
	}
}

function open(routes: Record<string, unknown> = {}) {
	const view = renderWithApp(<ReplayPanel meta={meta} />, { "GET /api/frames": { frames: [] }, ...routes });
	act(() => useAppStore.getState().setReplay({ plan: plan(30), pos: 4, playing: false, recording: false }));
	return view;
}

describe("ReplayPanel", () => {
	afterEach(() => {
		resetStore();
		vi.unstubAllGlobals();
	});

	it("closed from outside (the Timelapse tab, another atlas): a recording still running stops (CodeRabbit)", async () => {
		vi.stubGlobal("MediaRecorder", FakeRecorder);
		const canvas = { captureStream: () => ({}), clientWidth: 100, clientHeight: 100 };
		act(() => useAppStore.getState().setMap({ getCanvas: () => canvas } as unknown as MapLibreMap));
		const { user } = open();
		await user.click(screen.getByRole("button", { name: "Export" }));
		await user.click(await screen.findByRole("menuitem", { name: /Record the screen/ }));
		expect(FakeRecorder.last?.state).toBe("recording");
		act(() => useAppStore.getState().setReplay(null));
		expect(FakeRecorder.last?.stops).toBe(1);
	});

	it("sends settings changes one after another: the last answer shown is the last change's (CodeRabbit)", async () => {
		let first: (p: ReplayPlan) => void = () => {};
		const answers = [
			new Promise<ReplayPlan>((r) => {
				first = r;
			}),
			Promise.resolve(plan(60)),
		];
		let n = 0;
		const { user, calls } = open({ "PATCH /api/replay": () => answers[n++] });
		const box = screen.getByRole("spinbutton", { name: "length (s)" });
		await user.clear(box);
		await user.type(box, "45{Enter}");
		await user.clear(box);
		await user.type(box, "60{Enter}");
		expect(calls.filter((c) => c.path === "/api/replay")).toHaveLength(1); // the second waits for the first
		await act(async () => first(plan(45)));
		await waitFor(() => expect(useAppStore.getState().replay?.plan.settings.length).toBe(60));
		expect(calls.filter((c) => c.path === "/api/replay").map((c) => c.body)).toEqual([{ length: 45 }, { length: 60 }]);
	});

	it("a newer change that fails leaves the one before it that worked (CodeRabbit)", async () => {
		const answers = [plan(45), new Error("refused")];
		let n = 0;
		const { user } = open({ "PATCH /api/replay": () => answers[n++] });
		const box = screen.getByRole("spinbutton", { name: "length (s)" });
		await user.clear(box);
		await user.type(box, "45{Enter}");
		await user.clear(box);
		await user.type(box, "60{Enter}");
		await waitFor(() => expect(useAppStore.getState().error).toBeTruthy());
		expect(useAppStore.getState().replay?.plan.settings.length).toBe(45);
	});

	it("a change answering after the timelapse closed doesn't open it again", async () => {
		let answer: (p: ReplayPlan) => void = () => {};
		const { user } = open({
			"PATCH /api/replay": () =>
				new Promise<ReplayPlan>((r) => {
					answer = r;
				}),
		});
		const box = screen.getByRole("spinbutton", { name: "length (s)" });
		await user.clear(box);
		await user.type(box, "70{Enter}");
		act(() => useAppStore.getState().setReplay(null));
		await act(async () => answer(plan(70)));
		expect(useAppStore.getState().replay).toBeNull();
	});
});
