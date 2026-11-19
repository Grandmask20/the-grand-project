import type { Map as MapLibreMap } from "maplibre-gl";
import { describe, expect, it, vi } from "vitest";
import { PickQueue, pickBox, pickPixel } from "@/logic/PickPass";

type GL = WebGLRenderingContext;
const gl = (w: number, h: number) => ({ drawingBufferWidth: w, drawingBufferHeight: h }) as unknown as GL;
const map = (cssWidth: number) =>
	({ getCanvas: () => ({ clientWidth: cssWidth }), triggerRepaint: vi.fn() }) as unknown as MapLibreMap;

describe("PickQueue", () => {
	it("answers every click: a second one joins the first, and a layer emptied or removed answers nothing", async () => {
		const q = new PickQueue<number | null>(null);
		const m = map(100);
		const a = q.ask(m, true, 1, 1);
		const b = q.ask(m, true, 2, 2); // (it replaced the first, which never finished)
		const reqs = q.take();
		expect(reqs.map((r) => r.x)).toEqual([1, 2]);
		reqs[0].done(5);
		reqs[1].done(6);
		expect([await a, await b]).toEqual([5, 6]);
		const c = q.ask(m, true, 3, 3);
		q.settle(); // the layer emptied or went away before its frame
		expect(await c).toBeNull();
		expect(await q.ask(m, false, 0, 0)).toBeNull(); // nothing drawn: answered at once
	});
});

describe("pickPixel / pickBox", () => {
	it("floor the click to its pixel and keep it inside the picture", () => {
		const g = gl(200, 100); // twice the css size
		expect(pickPixel(g, map(100), 10.7, 0.2)).toEqual({ px: 21, py: 99, ratio: 2 }); // (rounding read row 100)
		expect(pickPixel(g, map(100), 100, 50)).toEqual({ px: 199, py: 0, ratio: 2 });
		expect(pickBox(g, 2, 98, 6)).toEqual({ x0: 0, y0: 92, w: 9, h: 8 }); // cut at the edges, not past them
		expect(pickBox(g, 100, 50, 6)).toEqual({ x0: 94, y0: 44, w: 13, h: 13 });
	});
});
