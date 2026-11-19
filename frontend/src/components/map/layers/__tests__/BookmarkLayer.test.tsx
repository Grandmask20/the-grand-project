import { act, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { BookmarkLayer } from "@/components/map/layers/BookmarkLayer";
import { useAppStore } from "@/store/AppStore";
import { bookmarks } from "@/test/Fixtures";
import { features, geo, renderOnMap } from "@/test/RenderOnMap";

vi.mock("react-map-gl/maplibre", () => import("@/test/ReactMapGlMock"));

describe("BookmarkLayer", () => {
	it("draws the bookmarks shown, and hides them while the timelapse plays", async () => {
		const { fm } = renderOnMap(<BookmarkLayer />, { "GET /api/bookmarks": bookmarks });
		await waitFor(() => expect(features(fm, "bookmarks")).toHaveLength(1));
		const f = features(fm, "bookmarks")[0];
		expect(f.geometry).toEqual({ type: "Point", coordinates: geo.toLngLat(10, 20) });
		expect(f.properties).toEqual({ id: 0, name: "big boss" });
		expect(fm.layers[0].layout.visibility).toBe("visible");
		act(() => useAppStore.setState({ replay: { pos: 1, plan: {} } as never }));
		expect(fm.layers[0].layout.visibility).toBe("none");
	});
});
