import { describe, expect, it } from "vitest";
import { Geo } from "@/logic/Geo";
import { boxLine, collection, EMPTY, line, point } from "@/logic/map/Features";
import { mapInfo } from "@/test/Fixtures";

const geo = new Geo(mapInfo);

describe("Features", () => {
	it("makes points, lines and collections", () => {
		expect(point([1, 2], { id: 3 })).toEqual({
			type: "Feature",
			geometry: { type: "Point", coordinates: [1, 2] },
			properties: { id: 3 },
		});
		expect(
			line([
				[0, 0],
				[1, 1],
			]).geometry,
		).toEqual({
			type: "LineString",
			coordinates: [
				[0, 0],
				[1, 1],
			],
		});
		expect(collection([])).toEqual(EMPTY);
	});

	it("outlines a box in atlas units, closed", () => {
		const f = boxLine(geo, [0, 0, 100, 50]);
		const coords = (f.geometry as GeoJSON.LineString).coordinates;
		expect(coords[0]).toEqual(geo.toLngLat(0, 0));
		expect(coords[2]).toEqual(geo.toLngLat(100, 50));
		expect(coords.at(-1)).toEqual(coords[0]);
	});
});
