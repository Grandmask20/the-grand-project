import { LngLat, type Map as MapLibreMap } from "maplibre-gl";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { type ErrorEvent, type MapEvent, Map as MapGL } from "react-map-gl/maplibre";
import { Button } from "@/components/ui/button";
import type { Meta } from "@/domain/app/Meta";
import type { MapInfo } from "@/domain/map/MapInfo";
import { PART_QUIET_S, useParts } from "@/hooks/app/UseParts";
import { MapViewContext } from "@/hooks/map/UseMapView";
import { Geo } from "@/logic/Geo";
import { mapStyle } from "@/logic/map/LayerOrder";
import { useAppStore } from "@/store/AppStore";
import { MapControls } from "./controls/MapControls";
import { FrameRecorder } from "./FrameRecorder";
import { AtlasLayers } from "./layers/AtlasLayers";
import { BookmarkLayer } from "./layers/BookmarkLayer";
import { DebugMarkLayers } from "./layers/DebugMarkLayers";
import { GhostLayers } from "./layers/GhostLayers";
import { QuestionLayers } from "./layers/QuestionLayers";
import { RecentLayer } from "./layers/RecentLayer";
import { ReplayFog } from "./layers/ReplayFog";
import { RouteLayers } from "./layers/RouteLayers";
import { SelectionLayers } from "./layers/SelectionLayers";
import { TintPicture } from "./layers/TintPicture";
import { MapCamera } from "./MapCamera";
import { MapInteraction } from "./MapInteraction";
import { MapLabels } from "./MapLabels";
import { MapPan } from "./MapPan";
import { MapSprites } from "./MapSprites";
import { PlayerMarker } from "./PlayerMarker";
import { TileSources } from "./sources/TileSources";
import { Scene3D } from "./three/Scene3D";

/** Web Mercator's last latitude: a centre further north or south has no place on the map. */
const MAX_LAT = 85.051129;

interface Props {
	info: MapInfo;
	meta: Meta;
}

const PART_NAMES: Record<string, string> = { map_image: "Map image", model: "Map nodes, paths, icons and biomes" };

/** The map: react-map-gl's MapLibre map on the app's tiles, with everything the page draws over them. Made once per
 * grid (the parent remounts it on a new one). */
export function AtlasMap({ info, meta }: Props) {
	const [geo] = useState(() => new Geo(info));
	const view = useMemo(() => ({ info, geo, meta }), [info, geo, meta]);
	const setStoreMap = useAppStore((s) => s.setMap);
	const [map, setMap] = useState<MapLibreMap | null>(null);
	const [tileError, setTileError] = useState<string | null>(null);
	// the map couldn't be made at all (no WebGL here): it never loads, so it says why, with a way to try again
	const [startError, setStartError] = useState<string | null>(null);
	const loaded = useRef(false);
	const { shown, show, parts, failed, ready } = useShown(map, tileError ?? startError);

	// made once: where the map was (kept when it is made again), else the whole atlas
	const [initialViewState] = useState(() => {
		const cam = useAppStore.getState().camera;
		if (!cam) return { bounds: info.bounds, fitBoundsOptions: { padding: 30 }, bearing: 0, pitch: 0 };
		const [longitude, latitude] = geo.toLngLat(cam.x, cam.y);
		return { longitude, latitude, zoom: geo.zoomFor(cam.px), bearing: cam.bearing, pitch: cam.pitch };
	});
	const [style] = useState(mapStyle);
	const [constrain] = useState(() => constrainTo(info, geo));

	const onLoad = useCallback(
		(e: MapEvent) => {
			loaded.current = true;
			setMap(e.target);
			setStoreMap(e.target);
		},
		[setStoreMap],
	);
	// tile errors from the map's creation: one before its load event (or while the model was still building) went
	// unseen, and the failure note never showed (CodeRabbit)
	const onError = useCallback((e: ErrorEvent & { sourceId?: string }) => {
		if (e.sourceId === "terrain" || e.sourceId === "atlas") setTileError(e.error?.message ?? "a map tile failed");
		// before it loaded and not a tile's: MapLibre couldn't make the map (react-map-gl hands its error here, and the
		// map was left blank behind "Show the map anyway": CodeRabbit)
		else if (!e.sourceId && !loaded.current) setStartError(e.error?.message ?? "the map could not start");
	}, []);
	useEffect(() => () => setStoreMap(null), [setStoreMap]);

	return (
		<div className="relative h-full w-full" data-testid="atlas-map">
			<MapGL
				mapStyle={style}
				initialViewState={initialViewState}
				transformConstrain={constrain}
				maxZoom={info.maxzoom}
				// every zoom level's tiles kept (MapLibre keeps 5): zoomed in deep, the zoomed-out ground was dropped and
				// zooming out showed the map nodes over black until it loaded again (user)
				maxTileCacheZoomLevels={info.zdeep + 1}
				maxPitch={75}
				renderWorldCopies={false}
				attributionControl={false}
				doubleClickZoom={false}
				dragPan={false} // MapPan's own
				// right-drag turns by sideways movement everywhere: MapLibre's default turns by the angle around the view's
				// centre once the mouse is 100 px above or below it and flips direction across it, so turning jumped and
				// reversed near the middle (user: too sensitive at some points, as if it turned a full circle). Passed on to
				// its rotate handler, at half MapLibre's speed (0.8 degrees per px was too fast: user); not in MapOptions'
				// type
				{...({ aroundCenter: false, rotateDegreesPerPixelMoved: 0.4 } as object)}
				onLoad={onLoad}
				onError={onError}
			>
				{map && (
					<MapViewContext.Provider value={view}>
						<MapControls />
						<MapPan />
						<MapSprites />
						<TileSources />
						<AtlasLayers />
						<TintPicture />
						<RecentLayer />
						<RouteLayers />
						<SelectionLayers />
						<BookmarkLayer />
						<DebugMarkLayers />
						<ReplayFog />
						<Scene3D />
						<GhostLayers />
						<QuestionLayers />
						<MapInteraction />
						<MapCamera />
						<MapLabels />
						<PlayerMarker />
						<FrameRecorder />
					</MapViewContext.Provider>
				)}
			</MapGL>
			{!shown && (
				<div className="absolute inset-0 z-10 flex flex-col items-center justify-center gap-2 bg-background text-sm text-muted-foreground">
					<p className="text-foreground">Loading atlas…</p>
					{Object.entries(parts).map(([name, p]) =>
						p ? (
							<p key={name}>
								{PART_NAMES[name] ?? name}:{" "}
								{p.state === "ready"
									? "ready"
									: p.state === "building" && p.quiet >= PART_QUIET_S
										? `no progress for ${Math.round(p.quiet)} s`
										: p.state === "building"
											? "building…"
											: "waiting"}
							</p>
						) : null,
					)}
					{ready && <p>Map tiles: loading…</p>}
					<Button variant="outline" size="sm" onClick={show}>
						Show the map anyway
					</Button>
				</div>
			)}
			{startError && (
				<div className="absolute inset-0 z-20 flex flex-col items-center justify-center gap-2 bg-background p-4 text-center text-sm">
					<p className="text-destructive">The map could not start: {startError}</p>
					<p className="text-muted-foreground">
						It needs WebGL: check that hardware acceleration is on in the browser's settings.
					</p>
					<Button variant="outline" size="sm" onClick={() => window.location.reload()}>
						Reload
					</Button>
				</div>
			)}
			{(failed.length > 0 || tileError) && (
				<div className="absolute top-2 left-2 z-10 max-w-md rounded border border-destructive bg-card p-2 text-xs text-destructive">
					{failed.map(([name, p]) => (
						<p key={name}>
							{PART_NAMES[name] ?? name} could not be made: {p?.error}
						</p>
					))}
					{tileError && <p>Map tiles could not load: {tileError}</p>}
				</div>
			)}
		</div>
	);
}

/**
 * Whether the map is shown yet. It is shown in one go, on what the app and MapLibre say, never on a timer (a big
 * atlas outgrew it, and a failed part only reached the log: banner, user): once every part is ready (map image,
 * model) and the map image and content tiles for the view have loaded, or as soon as a part or its tiles fail (shown
 * with what is there, and why). Shown as each came, the map image was up seconds before the rest (user). Only the
 * first draw waits.
 */
function useShown(map: MapLibreMap | null, tileError: string | null) {
	const [shown, setShown] = useState(false);
	const parts = useParts(!shown).data?.parts ?? {};
	const states = Object.values(parts);
	const failed = Object.entries(parts).filter(([, p]) => p?.state === "failed");
	const ready = states.length > 0 && states.every((p) => p?.state === "ready");

	useEffect(() => {
		if (failed.length || tileError) setShown(true);
	}, [failed.length, tileError]);
	useEffect(() => {
		if (!map || shown || !ready) return;
		// only what is shown is waited for: a source none of whose layers is ticked loads nothing (MapLibre skips it),
		// so with Ground off the map image isn't waited for (user: what isn't ticked mustn't slow the loading)
		const ticked = (id: string) =>
			map
				.getStyle()
				.layers.some((l) => "source" in l && l.source === id && (l.layout?.visibility ?? "visible") !== "none");
		const loaded = () =>
			map.isStyleLoaded() &&
			["terrain", "atlas"].every((id) => !map.getSource(id) || !ticked(id) || map.isSourceLoaded(id));
		const check = () => {
			if (loaded()) setShown(true);
		};
		// (the content tiles' address changes when the model is built: the drawing after it is the one waited for)
		map.on("idle", check);
		check();
		return () => {
			map.off("idle", check);
		};
	}, [map, ready, shown]);

	return { shown, show: () => setShown(true), parts, failed, ready };
}

/**
 * Pan freely, well past the atlas (user: the old window let you pan off it), but the centre stays within half an
 * atlas past its edges (MapLibre's world was too small a limit on a big atlas, and tilted the view reaches the
 * horizon: it panned off endlessly, user). Part of MapLibre's own constraint, so every camera change keeps to it:
 * corrected afterwards from move events, the two limits fought (a jump far out overflowed the stack).
 */
function constrainTo(info: MapInfo, geo: Geo) {
	const ax0 = info.grid.x0;
	const ay0 = info.grid.y0;
	const ax1 = ax0 + info.grid.width / info.grid.scale;
	const ay1 = ay0 + info.grid.height / info.grid.scale;
	const mx = (ax1 - ax0) * 0.5;
	const my = (ay1 - ay0) * 0.5;
	return (c: LngLat, zoom: number) => {
		const [x, y] = geo.toAtlas(c.lng, c.lat);
		const [lng, lat] = geo.toLngLat(
			Math.min(Math.max(x, ax0 - mx), ax1 + mx),
			Math.min(Math.max(y, ay0 - my), ay1 + my),
		);
		return {
			center: new LngLat(Math.min(Math.max(lng, -180), 180), Math.min(Math.max(lat, -MAX_LAT), MAX_LAT)),
			zoom,
		};
	};
}
