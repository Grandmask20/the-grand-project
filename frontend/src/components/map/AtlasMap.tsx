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

/** The furthest latitude Web Mercator can show. */
const MERCATOR_LAT = 85.0511;

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
		const [[w, s], [e, n]] = info.bounds;
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
			maxPitch: 75,
			renderWorldCopies: false,
			attributionControl: false,
			doubleClickZoom: false,
		});
		// pan freely, well past the atlas (user: the old window let you pan off it); a center more than an atlas-width
		// past an edge eases back. MapLibre's maxBounds kept the view in a corner beside the atlas instead (user):
		// zoomed out, the atlas fills much of MapLibre's world and the limit forced the view into its corner.
		const limit = () => {
			const c = m.getCenter();
			const v = m.getBounds();
			// room: an atlas-width plus a view-width past each edge, so zoomed far out you can still move it about
			const rx = e - w + (v.getEast() - v.getWest());
			const ry = n - s + (v.getNorth() - v.getSouth());
			const lng = Math.min(Math.max(c.lng, Math.max(w - rx, -180)), Math.min(e + rx, 180));
			const lat = Math.min(Math.max(c.lat, Math.max(s - ry, -MERCATOR_LAT)), Math.min(n + ry, MERCATOR_LAT));
			if (lng !== c.lng || lat !== c.lat) m.easeTo({ center: [lng, lat], duration: 300 });
		};
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
			else m.easeTo({ pitch: 60, bearing: m.getBearing() || -20, duration: 700 });
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
					<MapLook map={map} geo={geo} meta={meta} />
					<MapIcons map={map} geo={geo} info={info} />
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
