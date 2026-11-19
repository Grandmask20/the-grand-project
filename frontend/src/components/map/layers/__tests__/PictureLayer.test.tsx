import { render } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { PictureLayer } from "@/components/map/layers/PictureLayer";
import { fakeMap } from "./FakeMap";

let fake = fakeMap();
vi.mock("@/hooks/map/UseMapLibre", () => ({
	useMapLibre: () => fake.map,
	mapAlive: (m: { _removed: boolean }) => !m._removed,
}));

const at = (dx: number): [[number, number], [number, number], [number, number], [number, number]] => [
	[dx, 1],
	[dx + 1, 1],
	[dx + 1, 0],
	[dx, 0],
];

describe("PictureLayer", () => {
	beforeEach(() => {
		fake = fakeMap();
	});

	it("puts the picture in its place in the stack, moves it without loading it again, and takes it off", () => {
		const { rerender, unmount } = render(<PictureLayer id="preview" url="/a.png" corners={at(0)} opacity={0.5} />);
		expect(fake.sources.get("preview")).toMatchObject({ type: "image", url: "/a.png", coordinates: at(0) });
		expect(fake.layers).toEqual([
			{ id: "preview", before: "slot:preview", paint: expect.objectContaining({ "raster-opacity": 0.5 }) },
		]);

		rerender(<PictureLayer id="preview" url="/a.png" corners={at(5)} opacity={0.7} />);
		expect(fake.map.addSource).toHaveBeenCalledOnce(); // moved: not loaded again (it blinked: CodeRabbit)
		expect(fake.sources.get("preview")?.setCoordinates).toHaveBeenCalledWith(at(5));
		expect(fake.layers[0].paint["raster-opacity"]).toBe(0.7);

		rerender(<PictureLayer id="preview" url="/b.png" corners={at(5)} opacity={0.7} />);
		expect(fake.map.addSource).toHaveBeenCalledTimes(2); // another picture: made anew
		expect(fake.sources.get("preview")).toMatchObject({ url: "/b.png" });

		unmount();
		expect(fake.sources.size).toBe(0);
		expect(fake.layers).toEqual([]);
	});

	it("leaves a map that is gone alone", () => {
		const { unmount } = render(<PictureLayer id="ghost-picture" url="/a.png" corners={at(0)} opacity={1} />);
		fake.map._removed = true;
		unmount();
		expect(fake.map.removeLayer).not.toHaveBeenCalled();
	});
});
