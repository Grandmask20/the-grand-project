import { createContext, useContext } from "react";
import type { Meta } from "@/domain/app/Meta";
import type { MapInfo } from "@/domain/map/MapInfo";
import type { Geo } from "@/logic/Geo";

/** The open atlas's map: its grid and tiles (info), atlas units <-> longitude / latitude (geo) and the app's
 * colours (meta). Given by AtlasMap to everything drawn on the map. */
export interface MapView {
	info: MapInfo;
	geo: Geo;
	meta: Meta;
}

export const MapViewContext = createContext<MapView | null>(null);

/** The map's info, geo and meta (inside AtlasMap). */
export function useMapView(): MapView {
	const view = useContext(MapViewContext);
	if (!view) throw new Error("useMapView outside AtlasMap");
	return view;
}
