import { act, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { MapLabels } from "@/components/map/MapLabels";
import { useAppStore } from "@/store/AppStore";
import { fakeMap } from "@/test/FakeMap";
import { state } from "@/test/Fixtures";
import { renderOnMap } from "@/test/RenderOnMap";

vi.mock("react-map-gl/maplibre", () => import("@/test/ReactMapGlMock"));

const point = (layer: string, coords: [number, number], properties: Record<string, unknown>) => ({
	geometry: { type: "Point", coordinates: coords },
	layer: { id: layer },
	properties,
});

function withLayers() {
	const fm = fakeMap();
	for (const id of ["landmarks", "bookmarks", "marks-point", "icons"]) fm.map.addLayer({ id });
	Object.defineProperty(fm.map.getCanvas(), "clientWidth", { value: 1000 });
	Object.defineProperty(fm.map.getCanvas(), "clientHeight", { value: 800 });
	const drawn = [
		point("landmarks", [0, 0], { id: 1, name: "Old Tower", kind: "Tower" }),
		point("bookmarks", [2, 0], { id: 2, name: "farm" }),
		point("marks-point", [0, 2], { label: "D3" }),
		point("icons", [-2, 0], { id: 4, label: "Breach", step: 5 }),
	];
	fm.map.queryRenderedFeatures.mockImplementation(((q: { layers: string[] }) =>
		drawn.filter((f) => q.layers.includes(f.layer.id))) as () => unknown[]);
	return fm;
}

describe("MapLabels", () => {
	it("names landmarks, bookmarks and debug marks once the map is at rest", async () => {
		renderOnMap(<MapLabels />, {}, withLayers());
		expect(await screen.findByText("Old Tower")).toBeInTheDocument();
		expect(screen.getByText("★ farm")).toBeInTheDocument();
		expect(screen.getByText("D3")).toBeInTheDocument();
		expect(screen.queryByText("Breach")).toBeNull(); // icons zoomed out: too small for their names
	});

	it("hides them while the map moves, and lays them out again when it stops", async () => {
		const fm = withLayers();
		renderOnMap(<MapLabels />, {}, fm);
		await screen.findByText("Old Tower");
		act(() => fm.fire("movestart"));
		expect(screen.queryByText("Old Tower")).toBeNull();
		act(() => fm.fire("moveend"));
		expect(await screen.findByText("Old Tower")).toBeInTheDocument();
	});

	it("zoomed in, names icons too; while replaying, only those revealed", async () => {
		const fm = withLayers();
		fm.cam.zoom = 9;
		renderOnMap(<MapLabels />, {}, fm);
		expect(await screen.findByText("Breach")).toBeInTheDocument();
		act(() => useAppStore.setState({ replay: { pos: 2, plan: {} } as never }));
		act(() => fm.fire("idle"));
		await waitFor(() => expect(screen.queryByText("Breach")).toBeNull());
	});

	it("go when Names is switched off", async () => {
		const { queryClient } = renderOnMap(<MapLabels />, {}, withLayers());
		expect(await screen.findByText("Old Tower")).toBeInTheDocument();
		const layers = { ...state.settings.layers, Labels: false };
		act(() => queryClient.setQueryData(["state"], { ...state, settings: { ...state.settings, layers } }));
		await waitFor(() => expect(screen.queryByText("Old Tower")).toBeNull());
	});
});
