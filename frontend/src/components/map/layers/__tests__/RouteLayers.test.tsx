import { act, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { RouteLayers } from "@/components/map/layers/RouteLayers";
import { useAppStore } from "@/store/AppStore";
import { state } from "@/test/Fixtures";
import { features, renderOnMap } from "@/test/RenderOnMap";

vi.mock("react-map-gl/maplibre", () => import("@/test/ReactMapGlMock"));

const graph = {
	nodes: [
		{ id: 1, x: 0, y: 0, icons: [], status: "" },
		{ id: 2, x: 10, y: 0, icons: [], status: "" },
		{ id: 3, x: 20, y: 5, icons: [], status: "" },
	],
	edges: [
		{
			a: 1,
			b: 2,
			line: [
				[0, 0],
				[5, 1],
				[10, 0],
			],
		},
		{ a: 2, b: 3 },
	],
};

describe("RouteLayers", () => {
	it("draws the route along its paths and rings its maps", async () => {
		const { fm } = renderOnMap(<RouteLayers />, { "GET /api/graph": graph });
		expect(features(fm, "route")).toEqual([]);
		act(() => useAppStore.setState({ route: { path: [1, 2, 3] } as never }));
		await waitFor(() => expect(features(fm, "route")).toHaveLength(1));
		const line = features(fm, "route")[0].geometry as GeoJSON.LineString;
		expect(line.coordinates).toHaveLength(4); // the curved path's 3 points, then straight on
		const nodes = fm.sources.get("route-nodes")?.data as GeoJSON.FeatureCollection;
		expect(nodes.features.map((f) => f.properties?.id)).toEqual([2, 3]);
	});

	it("hides with its toggle", () => {
		const settings = { ...state.settings, layers: { ...state.settings.layers, Route: false } };
		const { fm } = renderOnMap(<RouteLayers />, { "GET /api/state": { ...state, settings } });
		expect(fm.layers.find((l) => l.id === "route")?.layout.visibility).toBe("none");
	});
});
