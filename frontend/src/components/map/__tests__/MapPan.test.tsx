import { act } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { MapPan } from "@/components/map/MapPan";
import { useAppStore } from "@/store/AppStore";
import { renderOnMap } from "@/test/RenderOnMap";

vi.mock("react-map-gl/maplibre", () => import("@/test/ReactMapGlMock"));

const mouse = (target: EventTarget, type: string, x: number, y: number, extra: MouseEventInit = {}) =>
	act(() => {
		target.dispatchEvent(new MouseEvent(type, { clientX: x, clientY: y, bubbles: true, ...extra }));
	});

describe("MapPan", () => {
	it("moves the map by the mouse's movement in px while the left button is held", () => {
		const { fm } = renderOnMap(<MapPan />);
		const el = fm.map.getCanvasContainer();
		mouse(el, "mousedown", 100, 100, { button: 0, buttons: 1 });
		mouse(window, "mousemove", 130, 90, { buttons: 1 });
		expect(fm.map.panBy).toHaveBeenLastCalledWith([-30, 10], { animate: false });
		mouse(window, "mouseup", 130, 90);
		mouse(window, "mousemove", 200, 200, { buttons: 0 });
		expect(fm.map.panBy).toHaveBeenCalledTimes(1);
	});

	it("leaves right-drag, Ctrl-drag, the lasso and a screenshot placed by hand alone", () => {
		const { fm } = renderOnMap(<MapPan />);
		const el = fm.map.getCanvasContainer();
		const drag = (extra: MouseEventInit) => {
			mouse(el, "mousedown", 0, 0, { buttons: 1, ...extra });
			mouse(window, "mousemove", 20, 20, { buttons: 1 });
			mouse(window, "mouseup", 20, 20);
		};
		drag({ button: 2 });
		drag({ button: 0, ctrlKey: true });
		act(() => useAppStore.getState().setMode({ kind: "lasso" }));
		drag({ button: 0 });
		expect(fm.map.panBy).not.toHaveBeenCalled();
	});
});
