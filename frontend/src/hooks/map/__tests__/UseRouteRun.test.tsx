import { act } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useRouteRun } from "@/hooks/map/UseRouteRun";
import type { LngLat } from "@/logic/Geo";
import { EMPTY } from "@/logic/map/Features";
import { DASHES } from "@/logic/RouteRun";
import { fakeMap } from "@/test/FakeMap";
import { renderOnMap } from "@/test/RenderOnMap";

vi.mock("react-map-gl/maplibre", () => import("@/test/ReactMapGlMock"));

const leg: LngLat[] = [
	[0, 0],
	[10, 0],
];

function Run({ legOf = leg, on = true }: { legOf?: LngLat[]; on?: boolean }) {
	useRouteRun(legOf, 2, on);
	return null;
}

let frames: FrameRequestCallback[] = [];
const step = (ms: number) =>
	act(() => {
		const now = frames;
		frames = [];
		for (const f of now) f(ms);
	});

describe("useRouteRun", () => {
	beforeEach(() => {
		frames = [];
		vi.spyOn(window, "requestAnimationFrame").mockImplementation((f) => frames.push(f));
		vi.spyOn(window, "cancelAnimationFrame").mockImplementation(() => {});
		vi.spyOn(performance, "now").mockReturnValue(0);
	});
	afterEach(() => vi.restoreAllMocks());

	const setup = () => {
		const fm = fakeMap();
		fm.map.addSource("route-runner", { type: "geojson", data: EMPTY });
		fm.map.addLayer({ id: "route-dash", type: "line", source: "route", paint: {} });
		return fm;
	};
	const runnerAt = (fm: ReturnType<typeof fakeMap>) => {
		const set = (fm.map.getSource("route-runner") as unknown as { setData: ReturnType<typeof vi.fn> }).setData;
		const fc = set.mock.calls.at(-1)?.[0] as GeoJSON.FeatureCollection;
		return (fc.features[0]?.geometry as GeoJSON.Point | undefined)?.coordinates;
	};

	it("walks the runner along its leg, frame by frame, and marches the dashes", () => {
		const fm = setup();
		renderOnMap(<Run />, {}, fm);
		step(0);
		expect(runnerAt(fm)).toEqual([0, 0]);
		step(450); // (half of one map's walk)
		expect(runnerAt(fm)).toEqual([5, 0]);
		expect(fm.map.setPaintProperty).toHaveBeenLastCalledWith("route-dash", "line-dasharray", DASHES[7]);
	});

	it("off, or no leg: no runner, nothing running", () => {
		const fm = setup();
		renderOnMap(<Run on={false} />, {}, fm);
		expect(frames).toHaveLength(0);
		expect(runnerAt(fm)).toBeUndefined();
	});

	it("less motion asked for: the runner waits at the leg's end, nothing moves", () => {
		vi.spyOn(window, "matchMedia").mockReturnValue({ matches: true } as MediaQueryList);
		const fm = setup();
		renderOnMap(<Run />, {}, fm);
		expect(frames).toHaveLength(0);
		expect(runnerAt(fm)).toEqual([10, 0]);
	});
});
