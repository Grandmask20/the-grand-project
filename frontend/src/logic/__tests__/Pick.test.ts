import { describe, expect, it } from "vitest";
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
