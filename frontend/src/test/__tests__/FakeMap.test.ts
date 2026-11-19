import { describe, expect, it, vi } from "vitest";
import { LAYER_ORDER, mapStyle } from "@/logic/map/LayerOrder";
import { fakeMap } from "@/test/FakeMap";

describe("FakeMap", () => {
	it("starts with the page's style: the background and every layer's slot", () => {
		const fm = fakeMap();
		expect(fm.map.getStyle().layers.map((l) => l.id)).toEqual(mapStyle().layers.map((l) => l.id));
		expect(fm.drawn()).toEqual([]);
		expect(fakeMap({ style: false }).map.getStyle().layers).toEqual([]);
	});

	it("puts a layer right under the one it is added before, as MapLibre", () => {
		const fm = fakeMap();
		fm.map.addLayer({ id: "selected" }, "slot:selected");
		fm.map.addLayer({ id: "paths" }, "slot:paths");
		const ids = fm.map.getStyle().layers.map((l) => l.id);
		expect(ids.indexOf("paths")).toBe(ids.indexOf("slot:paths") - 1);
		expect(fm.layerIds()).toEqual(["paths", "selected"]); // the stack's order, the style's own left out
		expect(LAYER_ORDER.indexOf("paths")).toBeLessThan(LAYER_ORDER.indexOf("selected"));
	});

	it("refuses a layer put before one it doesn't have: an error, nothing added, onAdd not called", () => {
		const fm = fakeMap({ style: false });
		const errors = vi.fn();
		fm.map.on("error", errors);
		const onAdd = vi.fn();
		fm.map.addLayer({ id: "x", onAdd } as never, "slot:x");
		expect(fm.layerIds()).toEqual([]);
		expect(onAdd).not.toHaveBeenCalled();
		expect(String((errors.mock.calls[0][0] as { error: Error }).error.message)).toContain(
			'non-existing layer "slot:x"',
		);
		fm.map.addLayer({ id: "y" }); // without one: on top
		expect(fm.layerIds()).toEqual(["y"]);
	});
});
