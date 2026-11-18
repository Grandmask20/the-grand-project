import { describe, expect, it } from "vitest";
import { selection3d } from "@/domain/map/Scene3D";
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

describe("selection3d", () => {
	it("rings a selected icon, lights up a selected map node's model (a landmark's by its map node)", () => {
		expect(selection3d({ kind: "icon", id: 7 })).toEqual({ icon: 7, model: 0 });
		expect(selection3d({ kind: "node", id: 4 })).toEqual({ icon: -1, model: pickCode("node", 4) });
		expect(selection3d({ kind: "landmark", id: 12, node: 4 })).toEqual({ icon: -1, model: pickCode("node", 4) });
		expect(selection3d({ kind: "landmark", id: 12, node: null })).toEqual({
			icon: -1,
			model: pickCode("landmark", 12),
		});
		expect(selection3d(null)).toEqual({ icon: -1, model: 0 });
	});
});
