import { render } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { CanvasPicture } from "@/components/map/layers/CanvasPicture";
import { fakeMap } from "./FakeMap";

let fake = fakeMap();
vi.mock("@/hooks/map/UseMapLibre", () => ({
	useMapLibre: () => fake.map,
	mapAlive: (m: { _removed: boolean }) => !m._removed,
}));

const corners: [[number, number], [number, number], [number, number], [number, number]] = [
	[0, 1],
	[1, 1],
	[1, 0],
	[0, 0],
];

/** A 2D context that only takes pictures (jsdom has no canvas drawing). */
function withContext() {
	const putImageData = vi.fn();
	vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockImplementation(
		() =>
			({
				createImageData: (w: number, h: number) => ({ data: new Uint8ClampedArray(4 * w * h) }),
				putImageData,
			}) as unknown as CanvasRenderingContext2D,
	);
	return putImageData;
}

describe("CanvasPicture", () => {
	beforeEach(() => {
		fake = fakeMap();
		vi.restoreAllMocks();
	});

	it("puts a still canvas in its slot and draws it, again whenever the drawing changes", () => {
		withContext();
		const draw = vi.fn();
		const { rerender, unmount } = render(
			<CanvasPicture id="fog-picture" width={4} height={2} corners={corners} draw={draw} resampling="linear" />,
		);
		const src = fake.sources.get("fog-picture");
		expect(src).toMatchObject({ type: "canvas", animate: false, coordinates: corners });
		expect((src?.canvas as HTMLCanvasElement | undefined)?.width).toBe(4);
		expect(fake.layers[0]).toMatchObject({ id: "fog-picture", before: "slot:fog-picture" });
		expect(fake.layers[0].paint["raster-resampling"]).toBe("linear");
		expect(draw).toHaveBeenCalledWith(expect.anything(), 4, 2);
		expect(src?.play).toHaveBeenCalled(); // read for a frame

		const again = vi.fn();
		rerender(
			<CanvasPicture id="fog-picture" width={4} height={2} corners={[...corners]} draw={again} resampling="linear" />,
		);
		expect(again).toHaveBeenCalledOnce();
		expect(fake.map.addSource).toHaveBeenCalledOnce(); // same size and place (a new array): the same canvas

		unmount();
		expect(fake.layers).toEqual([]);
		expect(fake.sources.size).toBe(0);
	});

	it("makes a new canvas for another size", () => {
		withContext();
		const draw = vi.fn();
		const { rerender } = render(<CanvasPicture id="tint-picture" width={4} height={2} corners={corners} draw={draw} />);
		rerender(<CanvasPicture id="tint-picture" width={8} height={2} corners={corners} draw={draw} opacity={0.3} />);
		expect(fake.map.addSource).toHaveBeenCalledTimes(2);
		expect((fake.sources.get("tint-picture")?.canvas as HTMLCanvasElement | undefined)?.width).toBe(8);
		expect(fake.layers).toHaveLength(1);
		expect(fake.layers[0].paint["raster-opacity"]).toBe(0.3);
	});
});
