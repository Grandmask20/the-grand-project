import { render } from "@testing-library/react";
import type { GeoJSONStoreFeatures } from "terra-draw";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { LassoDraw, lassoOf } from "@/components/map/draw/LassoDraw";
import { MapViewContext } from "@/hooks/map/UseMapView";
import { Geo } from "@/logic/Geo";
import { mapInfo, meta } from "@/test/Fixtures";

const geo = new Geo(mapInfo);

/** Terra Draw as far as the lasso uses it: its events, its features, started and stopped. */
const td = vi.hoisted(() => ({
	on: {} as Record<string, (...a: unknown[]) => void>,
	features: new Map<string | number, unknown>(),
	removed: [] as (string | number)[],
	mode: "",
	started: false,
	adapter: null as unknown,
	options: null as unknown,
}));
vi.mock("terra-draw", () => ({
	TerraDraw: class {
		constructor(o: { adapter: unknown }) {
			td.adapter = o.adapter;
		}
		on(ev: string, fn: (...a: unknown[]) => void) {
			td.on[ev] = fn;
		}
		off() {}
		start() {
			td.started = true;
		}
		stop() {
			td.started = false;
		}
		setMode(m: string) {
			td.mode = m;
		}
		getSnapshotFeature(id: string | number) {
			return td.features.get(id);
		}
		removeFeatures(ids: (string | number)[]) {
			td.removed.push(...ids);
		}
	},
	TerraDrawFreehandMode: class {
		constructor(o: unknown) {
			td.options = o;
		}
	},
}));
vi.mock("terra-draw-maplibre-gl-adapter", () => ({
	TerraDrawMapLibreGLAdapter: class {
		constructor(public config: unknown) {}
	},
}));
const map = { _removed: false, project: ([lng, lat]: [number, number]) => ({ x: lng, y: lat }) };
vi.mock("@/hooks/map/UseMapLibre", () => ({ useMapLibre: () => map, mapAlive: () => true }));

/** A drawn lasso: a closed ring through atlas points. */
function lasso(points: [number, number][]): GeoJSONStoreFeatures {
	const ring = [...points, points[0]].map(([x, y]) => geo.toLngLat(x, y));
	return { type: "Feature", geometry: { type: "Polygon", coordinates: [ring] }, properties: { mode: "freehand" } };
}

function draw(onStart = vi.fn(), onDrawn = vi.fn()) {
	const view = render(
		<MapViewContext.Provider value={{ geo, info: mapInfo, meta }}>
			<LassoDraw onStart={onStart} onDrawn={onDrawn} />
		</MapViewContext.Provider>,
	);
	return { ...view, onStart, onDrawn };
}

describe("LassoDraw", () => {
	beforeEach(() => {
		td.on = {};
		td.features.clear();
		td.removed.length = 0;
	});

	it("reads a drawn lasso back in atlas units, its ring not closed", () => {
		const pts =
			lassoOf(
				lasso([
					[0, 0],
					[100, 0],
					[100, 50],
				]),
				geo,
			) ?? [];
		expect(pts).toHaveLength(3);
		expect(pts[1][0]).toBeCloseTo(100, 6);
		expect(pts[2][1]).toBeCloseTo(50, 6);
		expect(lassoOf(undefined, geo)).toBeNull();
	});

	it("draws freehand as before (press, draw, let go), in the lasso's place, keys left to the page", () => {
		const { unmount } = draw();
		expect(td.started && td.mode).toBe("freehand");
		expect(td.options).toMatchObject({ drawInteraction: "click-drag", keyEvents: null });
		expect((td.adapter as { config: unknown }).config).toMatchObject({ renderBelowLayerId: "slot:lasso" });
		// MapLibre's double-click zoom stays off when Terra Draw stops (the page's double-click is its own)
		expect(() =>
			(td.adapter as { setDoubleClickToZoom: (on: boolean) => void }).setDoubleClickToZoom(true),
		).not.toThrow();
		unmount();
		expect(td.started).toBe(false);
	});

	it("hands the lasso drawn to the page, and a new one replaces it", () => {
		const { onStart, onDrawn } = draw();
		td.features.set(
			"a",
			lasso([
				[0, 0],
				[100, 0],
				[100, 50],
			]),
		);
		td.on.change(["a"], "create");
		expect(onStart).toHaveBeenCalledOnce();
		td.on.finish("a");
		const [points, at] = onDrawn.mock.calls[0];
		expect(points).toHaveLength(3);
		expect(at).toEqual(Object.fromEntries(Object.entries(map.project(geo.toLngLat(100, 50) as [number, number]))));
		td.on.change(["a"], "update"); // still drawing it: nothing new
		td.features.set("close", { type: "Feature", geometry: { type: "Point", coordinates: [0, 0] }, properties: {} });
		td.on.change(["close"], "create"); // the point it closes on: not a new lasso (it took the lasso away)
		expect(onStart).toHaveBeenCalledOnce();
		expect(td.removed).toEqual([]);
		td.features.set(
			"b",
			lasso([
				[0, 0],
				[10, 0],
				[10, 10],
			]),
		);
		td.on.change(["b"], "create");
		expect(td.removed).toEqual(["a"]);
		expect(onStart).toHaveBeenCalledTimes(2);
	});
});
