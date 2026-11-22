import { useEffect, useState } from "react";
import { Source } from "react-map-gl/maplibre";
import { useAppClient } from "@/hooks/app/UseAppClient";
import { useAppState } from "@/hooks/app/UseAppState";
import { useSettings } from "@/hooks/app/UseSettings";
import { useMapView } from "@/hooks/map/UseMapView";
import { ATLAS, layerOn, visibility } from "@/logic/map/AtlasLayers";
import {
	backdropVersion,
	groundAhead,
	PREFETCH_DELAY_MS,
	PREFETCH_PARALLEL,
	terrainVersion,
	vectorVersion,
} from "@/logic/map/Tiles";
import { useAppStore } from "@/store/AppStore";
import { MapLayer } from "../layers/MapLayer";

/**
 * The app's tiles: the map image (ground picture) and the vector tiles (map nodes, paths, icons, landmarks, biomes),
 * at their current versions, so a changed atlas, map image or filter is fetched again. The ground picture's layers
 * (and its backdrop) are drawn here; the vector tiles' layers by AtlasLayers.
 */
export function TileSources() {
	const app = useAppClient();
	const { info } = useMapView();
	const appState = useAppState().data;
	const now = appState?.map ?? info;
	const settings = useSettings();
	// the timelapse's tiles only in the tab playing it (other tabs, and this one after a reload, get the plain ones)
	const replay = useAppStore((s) => s.replay?.plan.token);
	const terrain = terrainVersion(now);
	const ground = app.terrainTiles(terrain);
	const bounds = [...info.bounds[0], ...info.bounds[1]] as [number, number, number, number];
	const picture = (settings?.ui.background ?? "picture") === "picture" && (!settings || layerOn(settings, "Terrain"));
	const before = useBackdrop(terrain, appState?.busy ?? false);

	useGroundAhead(ground, now.bounds);

	return (
		<>
			{/* the backdrop: the ground from before a job's changes, under the new, wherever the new hasn't come in
			    (user: a spot jumped to while adding stayed black). The map image's own levels only (the zoomed-out
			    ground, mostly fetched ahead already): never the sharp ground, which is slow to make */}
			<Source
				id="terrain-before"
				type="raster"
				tiles={[app.terrainTiles(before)]}
				tileSize={256}
				minzoom={0}
				maxzoom={info.zmax}
				bounds={bounds}
			>
				<MapLayer
					spec={{
						id: "terrain-before",
						type: "raster",
						source: "terrain-before",
						layout: { visibility: visibility(picture) },
						paint: { "raster-fade-duration": 0 },
					}}
				/>
			</Source>
			<Source
				id="terrain"
				type="raster"
				tiles={[ground]}
				tileSize={256}
				minzoom={0}
				maxzoom={info.zdeep}
				bounds={bounds}
			>
				{/* no fade-in: the map nodes and paths over it appear at once, and a fading ground showed them over black
				    first (user: zooming far out, the blobs came before the ground) */}
				<MapLayer
					spec={{
						id: "terrain",
						type: "raster",
						source: "terrain",
						layout: { visibility: visibility(picture) },
						paint: { "raster-fade-duration": 0 },
					}}
				/>
			</Source>
			<Source
				id={ATLAS}
				type="vector"
				tiles={[app.vectorTiles(vectorVersion(now), replay)]}
				minzoom={0}
				maxzoom={info.zmax}
				bounds={bounds}
			/>
		</>
	);
}

/** The backdrop's ground version: kept while a job runs, the current one otherwise (backdropVersion). */
function useBackdrop(current: string, busy: boolean): string {
	const [kept, setKept] = useState(current);
	const version = backdropVersion(kept, current, busy);
	useEffect(() => setKept(version), [version]);
	return version;
}

/** The zoomed-out ground fetched ahead (few tiles): zooming far out from close in, the map nodes and paths were there
 * long before the ground (user: blobs over black). After the first view has loaded, a few at a time. */
function useGroundAhead(template: string, atlasBounds: [[number, number], [number, number]]) {
	const bounds = JSON.stringify(atlasBounds); // (a new array with every state)
	useEffect(() => {
		const urls = groundAhead(template, JSON.parse(bounds));
		let stop = false;
		const next = async () => {
			for (let url = urls.shift(); url && !stop; url = urls.shift())
				try {
					await (await fetch(url)).arrayBuffer();
				} catch {
					// one tile that failed, also mid-body (CodeRabbit): the next one still comes
				}
		};
		const start = setTimeout(() => {
			for (let k = 0; k < PREFETCH_PARALLEL; k++) void next();
		}, PREFETCH_DELAY_MS);
		return () => {
			stop = true;
			clearTimeout(start);
		};
	}, [template, bounds]);
}
