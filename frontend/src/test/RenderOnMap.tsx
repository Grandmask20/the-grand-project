import type { ReactNode } from "react";
import { MapViewContext } from "@/hooks/map/UseMapView";
import { Geo } from "@/logic/Geo";
import { type FakeMap, fakeMap } from "./FakeMap";
import { mapInfo, meta } from "./Fixtures";
import { setMap } from "./ReactMapGlMock";
import { renderWithApp } from "./RenderWithApp";

export const geo = new Geo(mapInfo);

/**
 * Renders a part of the map on a fake map, with the app behind it (renderWithApp). The test file mocks react-map-gl:
 * vi.mock("react-map-gl/maplibre", () => import("@/test/ReactMapGlMock")).
 */
export function renderOnMap(ui: ReactNode, routes: Record<string, unknown> = {}, fm: FakeMap = fakeMap()) {
	setMap(fm);
	const wrap = (node: ReactNode) => (
		<MapViewContext.Provider value={{ info: mapInfo, geo, meta }}>{node}</MapViewContext.Provider>
	);
	const view = renderWithApp(wrap(ui), routes);
	return { ...view, fm, rerender: (node: ReactNode) => view.rerender(wrap(node)) };
}

/** The features a component put in a GeoJSON source of the fake map (none: []). */
export function features(fm: FakeMap, id: string): GeoJSON.Feature[] {
	const data = fm.sources.get(id)?.data as GeoJSON.FeatureCollection | GeoJSON.Feature | undefined;
	if (!data) return [];
	return data.type === "FeatureCollection" ? data.features : [data];
}
