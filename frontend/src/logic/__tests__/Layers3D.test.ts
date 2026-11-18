import { describe, expect, it } from "vitest";
import { scenePick } from "@/domain/map/Scene3D";
import { layerBelow } from "@/logic/Layers3D";
import { pickCode } from "@/logic/Pick";

describe("layerBelow", () => {
	it("puts each 3D layer in its own place, whichever was made first", () => {
		const on =
			(...ids: string[]) =>
			(id: string) =>
				ids.includes(id);
		// models made after paths and icons: under them (under the bookmarks, it was drawn over them)
		expect(layerBelow("models-3d-gl", on("paths-3d-gl", "icons-3d-gl"))).toBe("paths-3d-gl");
		expect(layerBelow("models-3d-gl", on("icons-3d-gl"))).toBe("icons-3d-gl");
		expect(layerBelow("paths-3d-gl", on("models-3d-gl"))).toBe("bookmarks");
		expect(layerBelow("icons-3d-gl", on("models-3d-gl", "paths-3d-gl"))).toBe("bookmarks");
	});
});

describe("scenePick", () => {
	it("reads a scene model's pick as its pick code", () => {
		expect(scenePick("node:4")).toBe(pickCode("node", 4));
		expect(scenePick("landmark:12")).toBe(pickCode("landmark", 12));
		expect(scenePick("")).toBe(0);
	});
});
