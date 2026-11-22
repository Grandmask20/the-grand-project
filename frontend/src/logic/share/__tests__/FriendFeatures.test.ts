import type { Feature, Geometry } from "geojson";
import { describe, expect, it } from "vitest";
import { Geo } from "@/logic/Geo";
import { friendFeatures, ICON_GAP, ICON_SCALE, ICON_UP } from "@/logic/share/FriendFeatures";
import { sharedAtlas } from "@/test/ShareAtlas";

const geo = new Geo(sharedAtlas.info);
/** A feature's coordinates (a point's or a line's). */
const at = (f: Feature<Geometry>) => (f.geometry as { coordinates: unknown }).coordinates;

describe("friendFeatures", () => {
	it("their maps and paths where their atlas has them: a path's own line, else straight", () => {
		const f = friendFeatures(sharedAtlas, null);
		expect(f.maps.features.map(at)).toEqual(sharedAtlas.nodes.map((n) => geo.toLngLat(n.x, n.y)));
		expect(f.paths.features.map(at)).toEqual([
			[geo.toLngLat(0, 0), geo.toLngLat(50, 10), geo.toLngLat(100, 0)],
			[geo.toLngLat(100, 0), geo.toLngLat(200, 50)],
		]);
		expect(f.landmarks.features[0].properties).toEqual({ label: "Vaal city", kind: "Vaal city" });
		expect(f.here.features).toEqual([]);
	});

	it("a map's icons in a row above it, each once, centred; every picture named once", () => {
		const f = friendFeatures(sharedAtlas, null);
		const first = f.icons.features.filter((i) => (at(i) as number[])[0] === geo.toLngLat(0, 0)[0]);
		expect(first.map((i) => i.properties)).toEqual([
			{ name: "Breach", off: [-ICON_GAP / 2 / ICON_SCALE, -ICON_UP / ICON_SCALE] },
			{ name: "Ritual", off: [ICON_GAP / 2 / ICON_SCALE, -ICON_UP / ICON_SCALE] },
		]);
		expect(f.icons.features).toHaveLength(3);
		expect(f.iconNames).toEqual(["Breach", "Ritual", "Abyss"]);
	});

	it("where they are, when they said", () => {
		const f = friendFeatures(sharedAtlas, { x: 100, y: 0, node: 2 });
		expect(f.here.features.map(at)).toEqual([geo.toLngLat(100, 0)]);
	});
});
