import { act } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { SelectionLayers } from "@/components/map/layers/SelectionLayers";
import { useAppStore } from "@/store/AppStore";
import { nodeInfo } from "@/test/Fixtures";
import { features, geo, renderOnMap } from "@/test/RenderOnMap";

vi.mock("react-map-gl/maplibre", () => import("@/test/ReactMapGlMock"));

const vis = (fm: ReturnType<typeof renderOnMap>["fm"], id: string) =>
	fm.layers.find((l) => l.id === id)?.layout.visibility;

describe("SelectionLayers", () => {
	it("rings the selection, Find's results and the go-to mark", () => {
		const { fm } = renderOnMap(<SelectionLayers />);
		expect(features(fm, "selected")).toEqual([]);
		act(() => {
			useAppStore.getState().select(nodeInfo);
			useAppStore.setState({
				results: [
					{ x: 1, y: 2 },
					{ x: 3, y: 4 },
				] as never,
				goto: [5, 6],
			});
		});
		expect(features(fm, "selected")[0].geometry).toEqual({ type: "Point", coordinates: geo.toLngLat(440, 200) });
		expect(features(fm, "hits")).toHaveLength(2);
		expect(features(fm, "goto")[0].geometry).toMatchObject({ coordinates: geo.toLngLat(5, 6) });
		expect(vis(fm, "selected")).toBe("visible");
		expect(fm.layers.map((l) => l.before)).toContain("slot:hits-edge");
	});

	it("lights a selected path up whole instead of ringing it", () => {
		const { fm } = renderOnMap(<SelectionLayers />);
		act(() =>
			useAppStore.getState().select({
				...nodeInfo,
				kind: "path",
				line: [
					[0, 0],
					[10, 0],
				],
			}),
		);
		expect(features(fm, "selected-path")[0].geometry.type).toBe("LineString");
		expect(vis(fm, "selected")).toBe("none");
	});

	it("tilted, a selected icon wears the 3D view's ring, not the flat one", async () => {
		const scene = { icons: [], paths: [], models: [] };
		const { fm } = renderOnMap(<SelectionLayers />, { "GET /api/scene3d": scene });
		act(() => {
			useAppStore.getState().select({ ...nodeInfo, kind: "icon", id: 3 });
			useAppStore.setState({ camera: { x: 0, y: 0, px: 1, bearing: 0, pitch: 50 } });
		});
		expect(vis(fm, "selected")).toBe("none");
	});
});
