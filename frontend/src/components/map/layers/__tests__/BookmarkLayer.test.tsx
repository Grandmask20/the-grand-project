import { act, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { BookmarkLayer } from "@/components/map/layers/BookmarkLayer";
import { useAppStore } from "@/store/AppStore";
import { bookmarks, state } from "@/test/Fixtures";
import { features, geo, renderOnMap } from "@/test/RenderOnMap";

vi.mock("react-map-gl/maplibre", () => import("@/test/ReactMapGlMock"));

describe("BookmarkLayer", () => {
	it("draws the bookmarks shown, and hides them while the timelapse plays", async () => {
		const { fm } = renderOnMap(<BookmarkLayer />, { "GET /api/bookmarks": bookmarks });
		await waitFor(() => expect(features(fm, "bookmarks")).toHaveLength(1));
		const f = features(fm, "bookmarks")[0];
		// on the icon row above its spot (View's default: icon_row_dy up)
		expect(f.geometry).toEqual({ type: "Point", coordinates: geo.toLngLat(10, 20 - 24) });
		expect(f.properties).toEqual({ id: 0, name: "big boss", icon: "" }); // (no look: the layer's colour)
		expect(fm.drawn()[0].layout.visibility).toBe("visible");
		act(() => useAppStore.setState({ replay: { pos: 1, plan: {} } as never }));
		expect(fm.drawn()[0].layout.visibility).toBe("none");
	});

	it("a pin in its look: its own, else its group's (user: colours and icons per bookmark and group)", async () => {
		const styled = {
			groups: [
				{
					name: "Boss",
					hidden: false,
					colour: "#00ff00",
					icon: "Breach",
					items: [
						{ id: 0, name: "own", note: "", x: 10, y: 20, created: "", hidden: false, shown: true, colour: "#ff0000" },
						{ id: 1, name: "plain", note: "", x: 30, y: 20, created: "", hidden: false, shown: true },
						{
							id: 2,
							name: "symbol",
							note: "",
							x: 50,
							y: 20,
							created: "",
							hidden: false,
							shown: true,
							icon: "sym:triangle",
						},
						{
							id: 3,
							name: "no ring",
							note: "",
							x: 70,
							y: 20,
							created: "",
							hidden: false,
							shown: true,
							icon: "Ritual",
							plain: true,
						},
					],
				},
			],
		};
		const { fm } = renderOnMap(<BookmarkLayer />, { "GET /api/bookmarks": styled });
		await waitFor(() => expect(features(fm, "bookmarks")).toHaveLength(4));
		expect(features(fm, "bookmarks").map((f) => f.properties)).toEqual([
			{ id: 0, name: "own", colour: "#ff0000", icon: "Breach", ring: true },
			{ id: 1, name: "plain", colour: "#00ff00", icon: "Breach", ring: true },
			// a symbol: its picture in its colour, no ring; a picture without a border (user)
			{ id: 2, name: "symbol", colour: "#00ff00", icon: "sym:triangle:#00ff00", ring: false },
			{ id: 3, name: "no ring", colour: "#00ff00", icon: "Ritual", ring: false },
		]);
		expect(fm.layers.some((l) => l.id === "bookmark-icons")).toBe(true);
	});

	it("a pin on the map node sits on its spot itself (View: bookmarks sit on the map node)", async () => {
		const st = {
			...state,
			settings: { ...state.settings, style: { ...state.settings.style, bookmark_at: "map node" } },
		};
		const { fm } = renderOnMap(<BookmarkLayer />, { "GET /api/bookmarks": bookmarks, "GET /api/state": st });
		await waitFor(() => expect(features(fm, "bookmarks")).toHaveLength(1));
		expect(features(fm, "bookmarks")[0].geometry).toEqual({ type: "Point", coordinates: geo.toLngLat(10, 20) });
	});
});
