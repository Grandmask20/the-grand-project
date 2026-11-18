import { describe, expect, it } from "vitest";
import { ringedIcon, type Scene3D } from "@/domain/map/Scene3D";
import { pickCode, pickItem } from "@/logic/Pick";

describe("model pick codes", () => {
	it("read back as the map node or landmark they were made for", () => {
		expect(pickItem(pickCode("node", 0))).toEqual({ kind: "node", id: 0 });
		expect(pickItem(pickCode("node", 24701))).toEqual({ kind: "node", id: 24701 });
		expect(pickItem(pickCode("landmark", 0))).toEqual({ kind: "landmark", id: 0 });
		expect(pickItem(pickCode("landmark", 771))).toEqual({ kind: "landmark", id: 771 });
		expect(pickItem(0)).toBeNull(); // nothing drawn there
		expect(pickCode("landmark", 3)).toBeLessThan(2 ** 24); // fits the three colour bytes
	});
});

describe("ringedIcon", () => {
	const scene = {
		icons: [
			[0, 0, 7, "Breach", 0, 0, -1, 3],
			[0, 0, 9, "MapBoss", 0, 0, -1, 4],
		],
		paths: [],
		models: [],
	} as unknown as Scene3D;
	it("rings the selected icon, or the icon on the selected map node or a landmark's map node", () => {
		expect(ringedIcon({ kind: "icon", id: 7 }, scene)).toBe(7);
		expect(ringedIcon({ kind: "node", id: 4 }, scene)).toBe(9);
		expect(ringedIcon({ kind: "landmark", id: 12, node: 4 }, scene)).toBe(9);
		expect(ringedIcon({ kind: "node", id: 5 }, scene)).toBe(-1); // no icon on it: the flat ring
		expect(ringedIcon(null, scene)).toBe(-1);
	});
});
