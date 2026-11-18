import type { Map as MapLibreMap, RasterTileSource, VectorTileSource } from "maplibre-gl";
import { useEffect } from "react";
import type { MapInfo } from "@/domain/map/MapInfo";
import { useAppClient } from "@/hooks/app/UseAppClient";
import { useAppState } from "@/hooks/app/UseAppState";

/** The vector tiles' version: they change with the model, the filters and the map image (its ground shapes). */
export function vectorVersion(info: Pick<MapInfo, "model_version" | "filter_version" | "terrain_version">): string {
	return `${info.model_version}-${info.filter_version}-${info.terrain_version}`;
}

/** Points the map's tile sources at the current versions (a changed atlas, map image or filter is fetched again). */
export function MapTiles({ map }: { map: MapLibreMap }) {
	const app = useAppClient();
	const info = useAppState().data?.map;
	const terrain = info?.terrain_version;
	const vector = info ? vectorVersion(info) : null;

	useEffect(() => {
		if (terrain === undefined) return;
		(map.getSource("terrain") as RasterTileSource | undefined)?.setTiles([app.terrainTiles(terrain)]);
	}, [map, app, terrain]);

	useEffect(() => {
		if (vector === null) return;
		(map.getSource("atlas") as VectorTileSource | undefined)?.setTiles([app.vectorTiles(vector)]);
	}, [map, app, vector]);

	return null;
}
