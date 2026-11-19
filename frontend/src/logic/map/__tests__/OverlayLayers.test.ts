import { describe, expect, it } from "vitest";
import { Geo } from "@/logic/Geo";
import {
	bookmarkLayer,
	hitLayers,
	markLayers,
	outlineLayer,
	recentLayer,
	routeLayers,
	selectionLayers,
} from "@/logic/map/OverlayLayers";
import { mapInfo, meta } from "@/test/Fixtures";

const geo = new Geo(mapInfo);
const vis = (s: { layout?: unknown }) => (s.layout as { visibility?: string } | undefined)?.visibility;

describe("OverlayLayers", () => {
	it("shows or hides each by its toggle", () => {
		expect(vis(recentLayer(meta, false))).toBe("none");
		expect(vis(bookmarkLayer(geo, meta, true))).toBe("visible");
		for (const s of markLayers(false)) expect(vis(s)).toBe("none");
		const route = routeLayers(geo, false);
		for (const s of [...route.line, route.nodes]) expect(vis(s)).toBe("none");
	});

	it("draws each over the source of its own name, the route's over the route", () => {
		expect(bookmarkLayer(geo, meta, true)).toMatchObject({ id: "bookmarks", source: "bookmarks" });
		expect(routeLayers(geo, true).line.map((s) => [s.id, "source" in s && s.source])).toEqual([
			["route-casing", "route"],
			["route", "route"],
		]);
		expect(hitLayers(geo, meta).map((s) => s.id)).toEqual(["hits-edge", "hits"]);
	});

	it("rings the selection unless lit up otherwise", () => {
		const [path, ring] = selectionLayers(geo, meta, false);
		expect(path.id).toBe("selected-path");
		expect(vis(ring)).toBe("none");
		expect(vis(selectionLayers(geo, meta, true)[1])).toBe("visible");
	});

	it("shows only the current step's screenshots coming in", () => {
		expect(outlineLayer(3).paint).toMatchObject({ "line-opacity": ["case", ["==", ["get", "step"], 3], 0.9, 0] });
		expect(outlineLayer(null).paint).toMatchObject({ "line-opacity": 0 }); // done, or not playing
	});

	it("dashes a missing path's debug line", () => {
		const [solid, dashed] = markLayers(true);
		expect(solid.paint).not.toHaveProperty("line-dasharray");
		expect(dashed.paint).toHaveProperty("line-dasharray");
	});
});
