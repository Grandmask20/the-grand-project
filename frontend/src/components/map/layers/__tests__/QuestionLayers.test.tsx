import { waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { QuestionLayers } from "@/components/map/layers/QuestionLayers";
import { state } from "@/test/Fixtures";
import { features, geo, renderOnMap } from "@/test/RenderOnMap";

vi.mock("react-map-gl/maplibre", () => import("@/test/ReactMapGlMock"));

describe("QuestionLayers", () => {
	it("shows a question's screenshot, the maps it agrees with, and snaps the map to it", async () => {
		const preview = {
			picture: 3,
			box: [0, 0, 100, 50] as [number, number, number, number],
			agree: [[10, 10] as [number, number]],
			near: [-20, -10, 40, 30] as [number, number, number, number],
		};
		const question = { id: 1, question: "Add it here?", preview };
		const { fm } = renderOnMap(<QuestionLayers />, { "GET /api/state": { ...state, questions: [question] } });
		expect(fm.sources.get("preview")).toMatchObject({
			url: "/api/pictures/3.png",
			coordinates: geo.corners(preview.box),
		});
		const agree = fm.sources.get("preview-agree")?.data as GeoJSON.FeatureCollection;
		expect(agree.features[0].geometry).toMatchObject({ coordinates: geo.toLngLat(10, 10) });
		expect(features(fm, "preview-line")).toHaveLength(1);
		// with what it joins, clear of the question's dialog
		await waitFor(() => expect(fm.map.fitBounds).toHaveBeenCalled());
		expect(fm.map.fitBounds.mock.calls[0][0]).toEqual(geo.boundsOf(-20, -10, 100, 50));
	});

	it("without a question, nothing", () => {
		const { fm } = renderOnMap(<QuestionLayers />);
		expect(fm.sources.has("preview")).toBe(false);
		expect(features(fm, "preview-line")).toEqual([]);
	});
});
