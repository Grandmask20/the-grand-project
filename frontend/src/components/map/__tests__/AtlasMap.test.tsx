import { screen } from "@testing-library/react";
import { useEffect } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AtlasMap } from "@/components/map/AtlasMap";
import { mapInfo, meta } from "@/test/Fixtures";
import { renderWithApp, resetStore } from "@/test/RenderWithApp";

// MapLibre itself can't load in jsdom (it starts a worker); the map's modules only need its names here
vi.mock("maplibre-gl", () => ({ LngLat: class {}, MercatorCoordinate: class {} }));

/** react-map-gl's <Map> as when MapLibre can't be made (no WebGL): no map, only its error. */
let fail: { error: { message: string }; sourceId?: string } | null = null;
vi.mock("react-map-gl/maplibre", () => ({
	Map: (props: { onError: (e: unknown) => void }) => {
		useEffect(() => {
			if (fail) props.onError(fail);
		}, [props]);
		return null;
	},
}));

const parts = { "GET /api/parts": { parts: { map_image: { state: "ready", quiet: 0, error: null } } } };

describe("AtlasMap", () => {
	afterEach(() => {
		resetStore();
		fail = null;
	});

	it("says why when the map can't start, with a way to try again", async () => {
		fail = { error: { message: "Failed to initialize WebGL" } };
		renderWithApp(<AtlasMap info={mapInfo} meta={meta} />, parts);
		expect(await screen.findByText("The map could not start: Failed to initialize WebGL")).toBeTruthy();
		expect(screen.getByRole("button", { name: "Reload" })).toBeTruthy();
		expect(screen.queryByText("Loading atlas…")).toBeNull(); // not waiting for a map that never comes
	});

	it("tells a tile's failure apart, the map still there", async () => {
		fail = { error: { message: "404" }, sourceId: "terrain" };
		renderWithApp(<AtlasMap info={mapInfo} meta={meta} />, parts);
		expect(await screen.findByText("Map tiles could not load: 404")).toBeTruthy();
		expect(screen.queryByText(/could not start/)).toBeNull();
	});
});
