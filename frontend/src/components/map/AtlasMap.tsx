import { FullscreenControl, LngLat, type Map as MapLibreMap, Map as MapView, NavigationControl } from "maplibre-gl";
import { useEffect, useRef, useState } from "react";
import nodePicture from "@/assets/map_node_icon.webp";
import { Button } from "@/components/ui/button";
import type { Meta } from "@/domain/app/Meta";
import type { MapInfo } from "@/domain/map/MapInfo";
import { useAppClient } from "@/hooks/app/UseAppClient";
import { PART_QUIET_S, useParts } from "@/hooks/app/UseParts";
import { Geo } from "@/logic/Geo";
import { baseStyle, squareImage } from "@/logic/MapStyle";
import { useAppStore } from "@/store/AppStore";
import { ButtonControl } from "./ButtonControl";
import { FrameRecorder } from "./FrameRecorder";
import { Icons3D } from "./Icons3D";
import { MapBookmarks } from "./MapBookmarks";
import { MapCamera } from "./MapCamera";
import { MapIcons } from "./MapIcons";
import { MapImages } from "./MapImages";
import { MapInteraction } from "./MapInteraction";
import { MapLabels } from "./MapLabels";
import { MapLook } from "./MapLook";
import { MapOverlays } from "./MapOverlays";
import { MapTiles, terrainVersion, vectorVersion } from "./MapTiles";
import { PlayerMarker } from "./PlayerMarker";
import { ReplayLayers } from "./ReplayLayers";

/**
 * The game's own atlas camera, for the 3D button: facing north, tilted so the ground's vanishing line sits where the
 * program measured it (core HORIZON: 2155 px above a 1080p screenshot's top, 2695 px above its middle). With
 * MapLibre's lens (36.87 deg high: a 1620 px focal length on 1080 px) that is atan(2695 / 1620) = 59 deg from straight
 * down. (It turned the map by -20 deg unless already turned, so it landed on different views: user.)
 */
const GAME_PITCH = 59;

/** Web Mercator's last latitude: a centre further north or south has no place on the map. */
const MAX_LAT = 85.051129;

interface Props {
	info: MapInfo;
	meta: Meta;
}

const PART_NAMES: Record<string, string> = { map_image: "Map image", model: "Map nodes, paths, icons and biomes" };

/** The map: MapLibre on the app's tiles, with everything the page draws over them. */
export function AtlasMap({ info, meta }: Props) {
	const app = useAppClient();
	const box = useRef<HTMLDivElement>(null);
	const [map, setMap] = useState<MapLibreMap | null>(null);
	const [geo] = useState(() => new Geo(info));
	const setStoreMap = useAppStore((s) => s.setMap);
	const [shown, setShown] = useState(false);
	const [tileError, setTileError] = useState<string | null>(null);
	const parts = useParts(!shown).data?.parts ?? {};
	const states = Object.values(parts);
	const failed = Object.entries(parts).filter(([, p]) => p?.state === "failed");
	const ready = states.length > 0 && states.every((p) => p?.state === "ready");

	// the map is shown in one go, on what the app and MapLibre say, never on a timer (a big atlas outgrew it, and a
	// failed part only reached the log: banner, user): once every part is ready (map image, model) and the map image
	// and content tiles for the view have loaded, or as soon as a part or its tiles fail (shown with what is there,
	// and why). Shown as each came, the map image was up seconds before the rest (user). Only the first draw waits.
	useEffect(() => {
		if (failed.length || tileError) setShown(true);
	}, [failed.length, tileError]);
	// tile errors from the start: one while the model was still building came before the wait began, and went
	// unseen (CodeRabbit)
	useEffect(() => {
		if (!map) return;
		const failedTile = (e: { sourceId?: string; error?: { message?: string } }) => {
			if (e.sourceId === "terrain" || e.sourceId === "atlas") setTileError(e.error?.message ?? "a map tile failed");
		};
		map.on("error", failedTile);
		return () => {
			map.off("error", failedTile);
		};
	}, [map]);
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

	// biome-ignore lint/correctness/useExhaustiveDependencies: made once per grid (the parent remounts on a new one)
	useEffect(() => {
		if (!box.current) return;
		const cam = useAppStore.getState().camera;
		// pan freely, well past the atlas (user: the old window let you pan off it), but the centre stays within half
		// an atlas past its edges (MapLibre's world was too small a limit on a big atlas, and tilted the view reaches
		// the horizon: it panned off endlessly, user). Part of MapLibre's own constraint, so every camera change keeps
		// to it: corrected afterwards from move events, the two limits fought (a jump far out overflowed the stack)
		const ax0 = info.grid.x0;
		const ay0 = info.grid.y0;
		const ax1 = ax0 + info.grid.width / info.grid.scale;
		const ay1 = ay0 + info.grid.height / info.grid.scale;
		const mx = (ax1 - ax0) * 0.5;
		const my = (ay1 - ay0) * 0.5;
		const constrain = (c: LngLat, zoom: number) => {
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
		const m = new MapView({
			transformConstrain: constrain,
			container: box.current,
			style: baseStyle(info, geo, meta, app.terrainTiles(terrainVersion(info)), app.vectorTiles(vectorVersion(info))),
			bounds: cam ? undefined : info.bounds,
			center: cam ? geo.toLngLat(cam.x, cam.y) : undefined,
			zoom: cam ? geo.zoomFor(cam.px) : undefined,
			bearing: cam?.bearing ?? 0,
			pitch: cam?.pitch ?? 0,
			fitBoundsOptions: { padding: 30 },
			maxZoom: info.maxzoom,
			// every zoom level's tiles kept (MapLibre keeps 5): zoomed in deep, the zoomed-out ground was dropped and
			// zooming out showed the map nodes over black until it loaded again (user)
			maxTileCacheZoomLevels: info.zdeep + 1,
			maxPitch: 75,
			renderWorldCopies: false,
			attributionControl: false,
			doubleClickZoom: false,
			// right-drag turns by sideways movement everywhere: MapLibre's default turns by the angle around the view's
			// centre once the mouse is 100 px above or below it and flips direction across it, so turning jumped and
			// reversed near the middle (user: too sensitive at some points, as if it turned a full circle). Passed on to
			// its rotate handler; not in MapOptions' type
			// and at half MapLibre's speed (0.8 degrees per px was too fast: user)
			...({ aroundCenter: false, rotateDegreesPerPixelMoved: 0.4 } as object),
		});
		// panning: the mouse's movement in px moves the map at the scale of the view's centre. MapLibre's own drag
		// keeps the grabbed ground point under the mouse, which near the horizon moved further and further with
		// every px (user: it sped up endlessly)
		m.dragPan.disable();
		const canvas = m.getCanvasContainer();
		let last: [number, number] | null = null;
		const down = (e: MouseEvent) => {
			const kind = useAppStore.getState().mode.kind;
			if (e.button !== 0 || e.ctrlKey || kind === "lasso" || kind === "ghost") return;
			last = [e.clientX, e.clientY];
		};
		const move = (e: MouseEvent) => {
			if (!last || !(e.buttons & 1)) {
				last = null;
				return;
			}
			const dx = e.clientX - last[0];
			const dy = e.clientY - last[1];
			last = [e.clientX, e.clientY];
			if (dx || dy) m.panBy([-dx, -dy], { animate: false });
		};
		const up = () => {
			last = null;
		};
		canvas.addEventListener("mousedown", down);
		window.addEventListener("mousemove", move);
		window.addEventListener("mouseup", up);
		m.addControl(new NavigationControl({ visualizePitch: true }), "top-right");
		m.addControl(
			new ButtonControl("⤢", "Fit the whole atlas (0)", () => m.fitBounds(info.bounds, { padding: 30 })),
			"top-right",
		);
		const three = new ButtonControl("3D", "3D view (or right-drag / Ctrl-drag to tilt and turn)", () => {
			if (m.getPitch() > 1) m.easeTo({ pitch: 0, bearing: 0, duration: 700 });
			else m.easeTo({ pitch: GAME_PITCH, bearing: 0, duration: 700 });
		});
		m.addControl(three, "top-right");
		m.addControl(new FullscreenControl(), "top-right");
		m.on("pitch", () => three.setOn(m.getPitch() > 1));
		m.on("load", () => {
			if (!m.hasImage("node-square")) m.addImage("node-square", squareImage(), { sdf: true });
			if (!m.hasImage("node-square-solid")) m.addImage("node-square-solid", squareImage(true), { sdf: true });
			void m
				.loadImage(nodePicture)
				.then((img) => {
					if (!m.hasImage("node-picture")) m.addImage("node-picture", img.data);
				})
				.catch(() => undefined); // the "map icons" style then draws nothing
			setMap(m);
			setStoreMap(m);
		});
		return () => {
			canvas.removeEventListener("mousedown", down);
			window.removeEventListener("mousemove", move);
			window.removeEventListener("mouseup", up);
			setStoreMap(null);
			setMap(null);
			// removed once the parts drawn on it have taken their layers off: React runs a removed tree's clean-ups
			// from the top, so this one ran first and they asked a map already gone (the timelapse fog threw and
			// blanked the page when another atlas opened: user)
			queueMicrotask(() => m.remove());
		};
	}, []);

	return (
		<div className="relative h-full w-full" data-testid="atlas-map">
			{/* h-full, not absolute inset-0: MapLibre's stylesheet makes its container position: relative, which
			    turned the absolute box 0 px tall (a black map) */}
			<div ref={box} className="h-full w-full" />
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
					<Button variant="outline" size="sm" onClick={() => setShown(true)}>
						Show the map anyway
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
			{map && (
				<>
					<MapTiles map={map} />
					<MapBookmarks map={map} geo={geo} />
					<MapLook map={map} geo={geo} meta={meta} />
					<MapIcons map={map} geo={geo} info={info} />
					<Icons3D map={map} geo={geo} info={info} meta={meta} />
					<MapCamera map={map} geo={geo} info={info} />
					<MapOverlays map={map} geo={geo} />
					<MapImages map={map} geo={geo} />
					<ReplayLayers map={map} geo={geo} meta={meta} />
					<MapInteraction map={map} geo={geo} meta={meta} />
					<MapLabels map={map} geo={geo} info={info} meta={meta} />
					<PlayerMarker map={map} geo={geo} />
					<FrameRecorder map={map} />
				</>
			)}
		</div>
	);
}
