import { act, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { MapSprites } from "@/components/map/MapSprites";
import { state } from "@/test/Fixtures";
import { renderOnMap } from "@/test/RenderOnMap";

vi.mock("react-map-gl/maplibre", () => import("@/test/ReactMapGlMock"));

describe("MapSprites", () => {
	it("adds the map's own pictures", async () => {
		const { fm } = renderOnMap(<MapSprites />);
		expect(fm.images.has("node-square")).toBe(true);
		expect(fm.images.has("node-square-solid")).toBe(true);
		await waitFor(() => expect(fm.images.has("node-picture")).toBe(true));
	});

	it("hands out an icon picture blank at once, then puts the real one in its place", async () => {
		const { fm } = renderOnMap(<MapSprites />);
		act(() => fm.fire("styleimagemissing", { id: "Breach" }));
		expect(fm.map.addImage).toHaveBeenLastCalledWith("Breach", expect.objectContaining({ width: 64, height: 64 }));
		// removed and added (MapLibre lays out again the tiles using it: updated in place, those on screen kept the old)
		await waitFor(() => expect(fm.map.removeImage).toHaveBeenCalledWith("Breach"));
		expect(fm.map.addImage).toHaveBeenLastCalledWith("Breach", { width: 1, height: 1, data: new Uint8Array(4) });
		expect(fm.map.loadImage.mock.calls.at(-1)?.[0]).toContain("Breach");
		expect(fm.map.updateImage).not.toHaveBeenCalled();
		act(() => fm.fire("styleimagemissing", { id: "node-square" })); // its own: not an icon
		expect(fm.map.addImage.mock.calls.filter((c) => c[0] === "node-square")).toHaveLength(1);
	});

	it("puts the pictures asked for together in, after a moment", async () => {
		vi.useFakeTimers();
		try {
			const { fm } = renderOnMap(<MapSprites />);
			act(() => {
				fm.fire("styleimagemissing", { id: "Breach" });
				fm.fire("styleimagemissing", { id: "Ritual" });
			});
			await act(async () => {
				await vi.advanceTimersByTimeAsync(30);
			});
			expect(fm.map.removeImage).not.toHaveBeenCalled(); // still gathering
			await act(async () => {
				await vi.advanceTimersByTimeAsync(30);
			});
			expect(fm.map.removeImage.mock.calls.map((c) => c[0])).toEqual(["Breach", "Ritual"]);
		} finally {
			vi.useRealTimers();
		}
	});

	it("another icon style loads every picture again, and puts them in at once", async () => {
		const { fm, rerender, queryClient } = renderOnMap(<MapSprites />);
		act(() => {
			fm.fire("styleimagemissing", { id: "Ritual" });
			fm.fire("styleimagemissing", { id: "Breach" });
		});
		await waitFor(() => expect(fm.map.removeImage).toHaveBeenCalledTimes(2));
		act(() =>
			queryClient.setQueryData(["state"], {
				...state,
				settings: { ...state.settings, style: { ...state.settings.style, icon_style: "flat" } },
			}),
		);
		rerender(<MapSprites />);
		await waitFor(() => expect(fm.map.removeImage).toHaveBeenCalledTimes(4));
		const restyled = fm.map.loadImage.mock.calls.slice(-2).map((c) => c[0]);
		expect(restyled.every((url) => url.includes("flat"))).toBe(true);
	});
});
