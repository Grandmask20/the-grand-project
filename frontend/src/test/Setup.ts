import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";
import { resetStore } from "./RenderWithApp";

afterEach(() => {
	cleanup();
	resetStore();
});

// jsdom lacks these; Radix (select, checkbox, dialog) calls them.
class ResizeObserverStub {
	observe() {}
	unobserve() {}
	disconnect() {}
}
globalThis.ResizeObserver ??= ResizeObserverStub as unknown as typeof ResizeObserver;
Element.prototype.hasPointerCapture ??= () => false;
Element.prototype.setPointerCapture ??= () => {};
Element.prototype.releasePointerCapture ??= () => {};
Element.prototype.scrollIntoView ??= () => {};
window.scrollTo = () => {};
// MapLibre starts its worker from a blob URL when it loads (jsdom has none): its classes are usable in tests then
URL.createObjectURL ??= () => "blob:test";
// jsdom draws nothing on a canvas: a 2D context whose pictures are real pixel arrays and whose drawing calls do
// nothing, so the page's canvas pictures (Colour by, the fog, exports) run in tests
HTMLCanvasElement.prototype.getContext = function (this: HTMLCanvasElement, kind: string) {
	if (kind !== "2d") return null;
	const image = (w: number, h: number) => ({ data: new Uint8ClampedArray(4 * w * h), width: w, height: h });
	const own: Record<string, unknown> = {
		canvas: this,
		createImageData: image,
		getImageData: (_x: number, _y: number, w: number, h: number) => image(w, h),
		putImageData: () => {},
		measureText: (t: string) => ({ width: 7 * t.length }),
	};
	return new Proxy(own, {
		get: (t, k) => (typeof k === "string" && k in t ? t[k] : () => {}),
		set: () => true,
	});
} as unknown as typeof HTMLCanvasElement.prototype.getContext;
