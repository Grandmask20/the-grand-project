import type { Map as MapLibreMap } from "maplibre-gl";
import { describe, expect, it } from "vitest";
import { onNextRender, vp9Codec } from "@/logic/ReplayExport";

/** A map that only knows its events (once / off / fire) and its canvas. */
function fakeMap() {
	const handlers = new Map<string, Set<() => void>>();
	const map = {
		once: (ev: string, fn: () => void) => {
			const set = handlers.get(ev) ?? new Set();
			const wrap = () => {
				set.delete(wrap);
				fn();
			};
			(wrap as unknown as { fn: () => void }).fn = fn;
			set.add(wrap);
			handlers.set(ev, set);
		},
		off: (ev: string, fn: () => void) => {
			for (const w of handlers.get(ev) ?? [])
				if ((w as unknown as { fn: () => void }).fn === fn) handlers.get(ev)?.delete(w);
		},
		fire: (ev: string) => {
			for (const w of [...(handlers.get(ev) ?? [])]) w();
		},
		getCanvas: () => ({}) as HTMLCanvasElement,
		triggerRepaint: () => undefined,
	};
	return map;
}

describe("vp9Codec", () => {
	it("declares a level that holds the picture", () => {
		expect(vp9Codec(1280, 720, 30)).toBe("vp09.00.31.08");
		expect(vp9Codec(1920, 1080, 30)).toBe("vp09.00.40.08"); // (level 1.0 before, at any size)
		expect(vp9Codec(1920, 1080, 60)).toBe("vp09.00.41.08");
		expect(vp9Codec(3840, 2160, 30)).toBe("vp09.00.50.08");
	});
});

describe("onNextRender", () => {
	it("draws in the next frame, and fails (not waits forever) when drawing throws or the map goes", async () => {
		const m = fakeMap();
		let drawn = 0;
		const ok = onNextRender(m as unknown as MapLibreMap, () => drawn++);
		m.fire("render");
		await ok;
		expect(drawn).toBe(1);
		const bad = onNextRender(m as unknown as MapLibreMap, () => {
			throw new Error("draw failed");
		});
		m.fire("render");
		await expect(bad).rejects.toThrow("draw failed");
		const gone = onNextRender(m as unknown as MapLibreMap, () => drawn++);
		m.fire("remove");
		await expect(gone).rejects.toThrow("replaced");
		m.fire("render"); // (its draw is no longer waiting)
		expect(drawn).toBe(1);
	});
});
