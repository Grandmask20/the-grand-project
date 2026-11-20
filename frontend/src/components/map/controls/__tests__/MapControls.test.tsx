import { act } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { GAME_PITCH, MapControls } from "@/components/map/controls/MapControls";
import { mapInfo } from "@/test/Fixtures";
import { renderOnMap } from "@/test/RenderOnMap";

vi.mock("react-map-gl/maplibre", () => import("@/test/ReactMapGlMock"));

const button = (fm: ReturnType<typeof renderOnMap>["fm"], title: RegExp) =>
	[...fm.container.querySelectorAll("button")].find((b) => title.test(b.title)) as HTMLButtonElement;

describe("MapControls", () => {
	it("Fit shows the whole atlas", () => {
		const { fm } = renderOnMap(<MapControls />);
		act(() => button(fm, /^Fit the whole atlas/).click());
		expect(fm.map.fitBounds).toHaveBeenCalledWith(mapInfo.bounds, { padding: 30 });
	});

	it("3D tilts to the game's own camera and back, lit while tilted", () => {
		const { fm } = renderOnMap(<MapControls />);
		const three = button(fm, /^3D view/);
		expect(three.textContent).toBe("3D");
		act(() => three.click());
		expect(fm.cam).toMatchObject({ pitch: GAME_PITCH, bearing: 0 });
		expect(three.classList.contains("on")).toBe(true);
		act(() => three.click());
		expect(fm.cam.pitch).toBe(0);
		expect(three.classList.contains("on")).toBe(false);
	});

	it("takes its buttons off with the map", () => {
		const { fm, unmount } = renderOnMap(<MapControls />);
		expect(fm.controls.size).toBe(2);
		unmount();
		expect(fm.controls.size).toBe(0);
		expect(fm.container.querySelector("button")).toBeNull();
	});
});
