import { act, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { HoverPeek } from "@/components/map/HoverPeek";
import { useAppStore } from "@/store/AppStore";
import { types } from "@/test/Fixtures";
import { features, renderOnMap } from "@/test/RenderOnMap";

vi.mock("react-map-gl/maplibre", () => import("@/test/ReactMapGlMock"));

const graph = {
	nodes: [
		{ id: 1, x: 0, y: 0, icons: [], status: "" },
		{ id: 2, x: 10, y: 0, icons: ["Breach", "Breach"], status: "" },
		{ id: 3, x: 20, y: 0, icons: [], status: "" },
		{ id: 4, x: 90, y: 90, icons: [], status: "" },
	],
	edges: [
		{ a: 1, b: 2 },
		{ a: 2, b: 3 },
	],
};

const setup = () => {
	const r = renderOnMap(<HoverPeek />, { "GET /api/graph": graph, "GET /api/types": types });
	r.fm.map.addLayer({ id: "maps", type: "circle", source: "atlas" });
	return r;
};
const over = (fm: ReturnType<typeof setup>["fm"], id: number | null, buttons = 0) => {
	vi.mocked(fm.map.queryRenderedFeatures).mockReturnValue(id === null ? [] : [{ properties: { id } }]);
	act(() => fm.fire("mousemove", { point: { x: 100, y: 50 }, originalEvent: { buttons } }));
};

describe("HoverPeek", () => {
	it("a map under the mouse: it and its paths lit, its neighbours ringed, a tip naming it with its icons", async () => {
		const { fm } = setup();
		await new Promise((r) => setTimeout(r, 50)); // (the graph comes)
		over(fm, 2);
		const tip = await screen.findByRole("tooltip");
		expect(tip).toHaveTextContent("Map #2 · 2 paths");
		await waitFor(() => expect(tip).toHaveTextContent("Breach"));
		expect(tip.style.left).toBe("114px");
		const lit = features(fm, "hover-peek");
		expect(lit.filter((f) => f.geometry.type === "LineString")).toHaveLength(2);
		const maps = lit.filter((f) => f.geometry.type === "Point");
		expect(maps.map((f) => [f.properties?.id, f.properties?.here])).toEqual([
			[2, true],
			[1, false],
			[3, false],
		]);
	});

	it("off a map, the mouse out, a map mode on or a button held: nothing", async () => {
		const { fm } = setup();
		await new Promise((r) => setTimeout(r, 50));
		over(fm, 2);
		expect(screen.getByRole("tooltip")).toBeInTheDocument();
		over(fm, null);
		expect(screen.queryByRole("tooltip")).toBeNull();
		over(fm, 2);
		act(() => fm.fire("mouseout"));
		expect(screen.queryByRole("tooltip")).toBeNull();
		over(fm, 2, 1);
		expect(screen.queryByRole("tooltip")).toBeNull();
		act(() => useAppStore.getState().setMode({ kind: "lasso" }));
		over(fm, 2);
		expect(screen.queryByRole("tooltip")).toBeNull();
		act(() => useAppStore.getState().setMode({ kind: "normal" }));
	});
});
