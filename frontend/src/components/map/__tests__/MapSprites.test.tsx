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

	it("hands out an icon picture blank at once, then the real one in place", async () => {
		const { fm } = renderOnMap(<MapSprites />);
		act(() => fm.fire("styleimagemissing", { id: "Breach" }));
		expect(fm.map.addImage).toHaveBeenCalledWith("Breach", expect.objectContaining({ width: 64, height: 64 }));
		await waitFor(() => expect(fm.map.updateImage).toHaveBeenCalledWith("Breach", expect.anything()));
		expect(fm.map.loadImage.mock.calls.at(-1)?.[0]).toContain("Breach");
		act(() => fm.fire("styleimagemissing", { id: "node-square" })); // its own: not an icon
		expect(fm.map.addImage.mock.calls.filter((c) => c[0] === "node-square")).toHaveLength(1);
	});

	it("another icon style loads every picture again", async () => {
		const { fm, rerender, queryClient } = renderOnMap(<MapSprites />);
		act(() => fm.fire("styleimagemissing", { id: "Ritual" }));
		await waitFor(() => expect(fm.map.updateImage).toHaveBeenCalledTimes(1));
		act(() =>
			queryClient.setQueryData(["state"], {
				...state,
				settings: { ...state.settings, style: { ...state.settings.style, icon_style: "flat" } },
			}),
		);
		rerender(<MapSprites />);
		await waitFor(() => expect(fm.map.updateImage).toHaveBeenCalledTimes(2));
		expect(fm.map.loadImage.mock.calls.at(-1)?.[0]).toContain("flat");
	});
});
