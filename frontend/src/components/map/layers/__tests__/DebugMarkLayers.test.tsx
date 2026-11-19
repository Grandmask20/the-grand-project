import { waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { DebugMarkLayers } from "@/components/map/layers/DebugMarkLayers";
import { state } from "@/test/Fixtures";
import { features, renderOnMap } from "@/test/RenderOnMap";

vi.mock("react-map-gl/maplibre", () => import("@/test/ReactMapGlMock"));

const mark = (id: number, kind: string, maps: { id: number; x: number; y: number }[]) => ({
	id,
	time: "",
	kind,
	reason: "",
	note: "",
	x: 5,
	y: 5,
	maps,
	screenshots: [],
});

describe("DebugMarkLayers", () => {
	it("in debug mode, rings each mark and joins the two maps of a missing path", async () => {
		const marks = {
			enabled: true,
			reasons: {},
			file: "",
			marks: [
				mark(1, "missing path", [
					{ id: 1, x: 0, y: 0 },
					{ id: 2, x: 10, y: 0 },
				]),
				mark(2, "missing map", []),
			],
		};
		const { fm } = renderOnMap(<DebugMarkLayers />, {
			"GET /api/state": { ...state, debug: true },
			"GET /api/debug": marks,
		});
		await waitFor(() => expect(features(fm, "marks")).toHaveLength(3));
		const kinds = features(fm, "marks").map((f) => `${f.geometry.type} ${f.properties?.label}`);
		expect(kinds).toEqual(["LineString D1", "Point D1", "Point D2"]);
		expect(fm.layerIds()).toEqual(["marks-line", "marks-dashed", "marks-point"]);
	});
});
