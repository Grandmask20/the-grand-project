import { FullscreenControl, type Map as MapLibreMap, Map as MapView, NavigationControl } from "maplibre-gl";
import { useEffect, useRef, useState } from "react";
import nodePicture from "@/assets/map_node_icon.webp";
import type { Meta } from "@/domain/app/Meta";
import type { MapInfo } from "@/domain/map/MapInfo";
import { useAppClient } from "@/hooks/app/UseAppClient";
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

interface Props {
	info: MapInfo;
	meta: Meta;
}

/** The map: MapLibre on the app's tiles, with everything the page draws over them. */
export function AtlasMap({ info, meta }: Props) {
	const app = useAppClient();
	const box = useRef<HTMLDivElement>(null);
	const [map, setMap] = useState<MapLibreMap | null>(null);
	const [geo] = useState(() => new Geo(info));
	const setStoreMap = useAppStore((s) => s.setMap);

	// biome-ignore lint/correctness/useExhaustiveDependencies: made once per grid (the parent remounts on a new one)
	useEffect(() => {
		if (!box.current) return;
		const cam = useAppStore.getState().camera;
		const m = new MapView({
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
			...({ aroundCenter: false } as object),
		});
		// pan freely, well past the atlas (user: the old window let you pan off it); a center more than an atlas-width
		// past an edge eases back. MapLibre's maxBounds kept the view in a corner beside the atlas instead (user):
		// zoomed out, the atlas fills much of MapLibre's world and the limit forced the view into its corner.
		// pan limit in atlas units: the centre stays within half an atlas past its edges (MapLibre's world was too
		// small a limit on a big atlas, and tilted the view reaches the horizon: it panned off endlessly, user)
		const ax0 = info.grid.x0;
		const ay0 = info.grid.y0;
		const ax1 = ax0 + info.grid.width / info.grid.scale;
		const ay1 = ay0 + info.grid.height / info.grid.scale;
		const mx = (ax1 - ax0) * 0.5;
		const my = (ay1 - ay0) * 0.5;
		// once per move: setCenter fires another move, and where MapLibre's own limits (its world's latitudes) keep
		// the centre a hair off ours, the two corrected each other forever (a jump far out: stack overflow)
		let limiting = false;
		const limit = () => {
			if (limiting) return;
			const c = m.getCenter();
			const [x, y] = geo.toAtlas(c.lng, c.lat);
			const cx = Math.min(Math.max(x, ax0 - mx), ax1 + mx);
			const cy = Math.min(Math.max(y, ay0 - my), ay1 + my);
			if (Math.abs(cx - x) + Math.abs(cy - y) < 1e-3) return;
			limiting = true;
			try {
				m.setCenter(geo.toLngLat(cx, cy));
			} finally {
				limiting = false;
			}
		};
		m.on("drag", limit);
		m.on("move", limit);
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
		m.on("moveend", limit);
		// after the map is removed (another atlas opened) its layers and sources are simply gone: the parts of the page
		// that tidy up after it (the replay's fog) asked a removed map and threw, which blanked the page (user)
		const getLayer = m.getLayer.bind(m);
		const getSource = m.getSource.bind(m);
		m.getLayer = ((id: string) => (m.style ? getLayer(id) : undefined)) as typeof m.getLayer;
		m.getSource = ((id: string) => (m.style ? getSource(id) : undefined)) as typeof m.getSource;
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
			m.remove();
		};
	}, []);

	return (
		<div className="relative h-full w-full" data-testid="atlas-map">
			{/* h-full, not absolute inset-0: MapLibre's stylesheet makes its container position: relative, which
			    turned the absolute box 0 px tall (a black map) */}
			<div ref={box} className="h-full w-full" />
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
					<MapLabels map={map} meta={meta} />
					<PlayerMarker map={map} geo={geo} />
					<FrameRecorder map={map} />
				</>
			)}
		</div>
	);
}
