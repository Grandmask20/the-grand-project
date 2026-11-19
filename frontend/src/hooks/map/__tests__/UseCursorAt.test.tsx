import { act, screen } from "@testing-library/react";
import type { Map as MapLibreMap } from "maplibre-gl";
import { afterEach, describe, expect, it } from "vitest";
import type { MapInfo } from "@/domain/map/MapInfo";
import { useCursorAt } from "@/hooks/map/UseCursorAt";
import { Geo } from "@/logic/Geo";
import { useAppStore } from "@/store/AppStore";
import { state } from "@/test/Fixtures";
import { renderWithApp, resetStore } from "@/test/RenderWithApp";

const info = {
	grid: { x0: -300, y0: -200, scale: 0.5, width: 4000, height: 3000 },
	world: 16384,
	offset: 4096,
	zmax: 6,
} as unknown as MapInfo;

/** A map that only keeps its event listeners (mousemove / mouseout) and a zoom. */
function fakeMap() {
	const on = new Map<string, (e: unknown) => void>();
	return {
		map: {
			on: (ev: string, fn: (e: unknown) => void) => on.set(ev, fn),
			off: (ev: string) => on.delete(ev),
			getZoom: () => 3,
		} as unknown as MapLibreMap,
		fire: (ev: string, e?: unknown) => act(() => on.get(ev)?.(e)),
	};
}

function Probe() {
	return <p data-testid="at">{useCursorAt()}</p>;
}

describe("useCursorAt", () => {
	afterEach(resetStore);

	it("says where the mouse is on the atlas, and nothing once it leaves the map", () => {
		const { map, fire } = fakeMap();
		useAppStore.setState({ map });
		renderWithApp(<Probe />, { "GET /api/state": { ...state, map: info } });
		const [lng, lat] = new Geo(info).toLngLat(120, 80);
		fire("mousemove", { lngLat: { lng, lat } });
		expect(screen.getByTestId("at").textContent).toMatch(/^x 120 {2}y 80 {3}zoom /);
		fire("mouseout");
		expect(screen.getByTestId("at").textContent).toBe(""); // (it kept the last place: CodeRabbit)
	});
});
