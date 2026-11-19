import { screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { PlayerMarker } from "@/components/map/PlayerMarker";
import { state } from "@/test/Fixtures";
import { geo, renderOnMap } from "@/test/RenderOnMap";

vi.mock("react-map-gl/maplibre", () => import("@/test/ReactMapGlMock"));

describe("PlayerMarker", () => {
	it("marks your position, in the atlas it was set in", () => {
		const player = { x: 30, y: 40, node: 2, atlas: state.atlas?.path };
		renderOnMap(<PlayerMarker />, {
			"GET /api/state": { ...state, settings: { ...state.settings, ui: { ...state.settings.ui, player } } },
		});
		expect(screen.getByTitle("You are here")).toHaveClass("player-marker");
		expect(screen.getByTestId("marker").dataset.lnglat).toBe(geo.toLngLat(30, 40).join(","));
	});

	it("not set, or set in another atlas: nothing", () => {
		const player = { x: 30, y: 40, node: 2, atlas: "/other/atlas.json" };
		renderOnMap(<PlayerMarker />, {
			"GET /api/state": { ...state, settings: { ...state.settings, ui: { ...state.settings.ui, player } } },
		});
		expect(screen.queryByTitle("You are here")).toBeNull();
	});
});
