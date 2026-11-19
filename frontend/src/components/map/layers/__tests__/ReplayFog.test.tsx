import { act, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ReplayFog } from "@/components/map/layers/ReplayFog";
import { useAppStore } from "@/store/AppStore";
import { features, renderOnMap } from "@/test/RenderOnMap";

vi.mock("react-map-gl/maplibre", () => import("@/test/ReactMapGlMock"));

const corners: [[number, number], [number, number], [number, number], [number, number]] = [
	[0, 1],
	[1, 1],
	[1, 0],
	[0, 0],
];
const field = { w: 2, h: 1, top: 2, data: btoa(String.fromCharCode(0, 0, 255, 255)), corners };
const box: [number, number][] = [
	[0, 0],
	[10, 0],
	[10, 10],
];
const frames = { frames: [{ corners: box }, { corners: box }], order: [0, 1], ramp: [], sessions: [], heat_top: 1 };
const plan = (area: boolean) => ({ token: 1, n_steps: 2, area, step_of: [0, 1] });

describe("ReplayFog", () => {
	it("puts the fog over the map while the timelapse plays, and outlines the step's screenshots", async () => {
		const { fm } = renderOnMap(<ReplayFog />, { "GET /api/replay/fog": { field }, "GET /api/frames": frames });
		expect(fm.sources.has("fog-picture")).toBe(false);
		act(() => useAppStore.setState({ replay: { pos: 1, plan: plan(false) } as never }));
		await waitFor(() => expect(fm.sources.has("fog-picture")).toBe(true));
		expect(fm.layers.find((l) => l.id === "fog-picture")).toMatchObject({ before: "slot:fog-picture" });
		await waitFor(() => expect(features(fm, "outline")).toHaveLength(2));
		const outline = fm.layers.find((l) => l.id === "outline");
		expect(outline?.paint["line-opacity"]).toEqual(["case", ["==", ["get", "step"], 0], 0.9, 0]);
		act(() => useAppStore.setState({ replay: { pos: 2, plan: plan(false) } as never }));
		expect(fm.layers.find((l) => l.id === "outline")?.paint["line-opacity"]).toBe(0); // done
		act(() => useAppStore.setState({ replay: null }));
		expect(fm.sources.has("fog-picture")).toBe(false);
	});

	it("revealing by area, no outlines", async () => {
		const { fm } = renderOnMap(<ReplayFog />, { "GET /api/replay/fog": { field }, "GET /api/frames": frames });
		act(() => useAppStore.setState({ replay: { pos: 0.5, plan: plan(true) } as never }));
		await waitFor(() => expect(fm.sources.has("fog-picture")).toBe(true));
		expect(features(fm, "outline")).toEqual([]);
	});
});
