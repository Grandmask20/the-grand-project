import { waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { TintPicture } from "@/components/map/layers/TintPicture";
import { state } from "@/test/Fixtures";
import { renderOnMap } from "@/test/RenderOnMap";

vi.mock("react-map-gl/maplibre", () => import("@/test/ReactMapGlMock"));

const box: [number, number][] = [
	[0, 0],
	[100, 0],
	[100, 50],
	[0, 50],
];
const frames = {
	frames: [{ corners: box, session: 0, rank: 0 }],
	order: [0],
	ramp: ["#000000", "#ffffff"],
	sessions: ["#ff0000"],
	heat_top: 1,
};
const tinted = (age_tint: string) => ({
	...state,
	settings: { ...state.settings, style: { ...state.settings.style, age_tint } },
});

describe("TintPicture", () => {
	it("draws Colour by as one picture under the biomes, once the ground mask is in", async () => {
		const { fm } = renderOnMap(<TintPicture />, {
			"GET /api/state": tinted("by session"),
			"GET /api/frames": frames,
		});
		// (the ground mask is fetched straight, not through the fake app: none here, so it is drawn as it is)
		await waitFor(() => expect(fm.sources.has("tint-picture")).toBe(true));
		const layer = fm.layers.find((l) => l.id === "tint-picture");
		expect(layer).toMatchObject({ before: "slot:tint-picture" });
		expect(layer?.paint["raster-opacity"]).toBe(0.32); // meta.tint_alpha
	});

	it("times seen: at the heat picture's strength", async () => {
		const { fm } = renderOnMap(<TintPicture />, { "GET /api/state": tinted("times seen"), "GET /api/frames": frames });
		await waitFor(() => expect(fm.sources.has("tint-picture")).toBe(true));
		expect(fm.layers.find((l) => l.id === "tint-picture")?.paint["raster-opacity"]).toBe(0.38);
	});

	it("off: nothing", () => {
		const { fm } = renderOnMap(<TintPicture />, { "GET /api/frames": frames });
		expect(fm.sources.has("tint-picture")).toBe(false);
	});
});
